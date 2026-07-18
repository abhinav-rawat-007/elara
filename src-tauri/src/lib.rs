// Elara desktop shell.
//
// The Rust side stays thin: it spawns the Python backend ("the mind") as a
// child process on startup, makes sure it's killed when the app exits, gives
// Elara a system-tray life (close hides to tray instead of quitting), and
// registers a global hotkey to summon the window. All AI/voice work happens
// in the Python sidecar, which the React UI talks to over a WebSocket.

use std::process::{Child, Command};
use std::sync::Mutex;

use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent},
    Manager, State, WindowEvent,
};

#[cfg(target_os = "windows")]
use std::os::windows::process::CommandExt;
#[cfg(target_os = "windows")]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

/// Tie a spawned child's lifetime to this process on Windows.
///
/// The explicit `child.kill()` paths (tray Quit, quit_app) only fire on a clean
/// shutdown. When the app is stopped from the terminal — Ctrl+C during
/// `tauri dev`, the dev runner terminating us, a crash, or `taskkill` — those
/// never run and the backend orphans, holding port 8765. A Job Object with
/// KILL_ON_JOB_CLOSE fixes every case: the child is assigned to a job whose
/// only handle lives in this process, so the instant we die for any reason the
/// OS closes the handle and terminates everything in the job.
#[cfg(target_os = "windows")]
mod job {
    use std::os::windows::io::AsRawHandle;
    use std::process::Child;
    use std::sync::OnceLock;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };

    // The job handle is intentionally never closed — it must outlive nothing,
    // it must live exactly as long as the process. Stored as isize so it's
    // Send + Sync; cast back to HANDLE at the call site.
    static JOB: OnceLock<isize> = OnceLock::new();

    fn ensure_job() -> isize {
        *JOB.get_or_init(|| unsafe {
            let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
            if handle.is_null() {
                return 0;
            }
            let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            SetInformationJobObject(
                handle,
                JobObjectExtendedLimitInformation,
                &info as *const _ as *const core::ffi::c_void,
                std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
            );
            handle as isize
        })
    }

    /// Bind `child` to the kill-on-close job. Best-effort: if the job can't be
    /// created the app still runs, it just falls back to the explicit kills.
    pub fn bind(child: &Child) {
        let handle = ensure_job();
        if handle == 0 {
            return;
        }
        unsafe {
            AssignProcessToJobObject(handle as _, child.as_raw_handle() as _);
        }
    }
}

struct Backend(Mutex<Option<Child>>);

/// The per-launch secret that authorizes the UI to the backend. Minted once at
/// startup, handed to the Python child via ELARA_TOKEN, and to the webview via
/// the `backend_token` command — so only our own UI can drive Elara's tools.
struct BackendToken(String);

/// 24 random bytes, hex-encoded. Uses the OS CSPRNG.
fn generate_token() -> String {
    let mut buf = [0u8; 24];
    getrandom::getrandom(&mut buf).expect("OS RNG unavailable");
    buf.iter().map(|b| format!("{b:02x}")).collect()
}

/// Build the command that launches the backend, passing it the auth token.
///
/// Prefers a bundled `elara-backend` sidecar sitting next to the app binary
/// (packaged builds); falls back to running the source with the venv's Python
/// (developer machines), so `pnpm tauri dev` keeps working with no extra steps.
fn backend_command(token: &str) -> Option<Command> {
    // 1. Packaged: sidecar exe next to the app executable.
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            let sidecar = dir.join(if cfg!(windows) {
                "elara-backend.exe"
            } else {
                "elara-backend"
            });
            if sidecar.exists() {
                let mut cmd = Command::new(&sidecar);
                cmd.current_dir(dir);
                cmd.env("ELARA_TOKEN", token);
                return Some(cmd);
            }
        }
    }

    // 2. Dev: run backend/main.py with the venv interpreter (or PATH `python`).
    let manifest = env!("CARGO_MANIFEST_DIR");
    let root = std::path::Path::new(manifest).parent()?.to_path_buf();
    let backend_dir = root.join("backend");
    let venv_python = backend_dir.join(".venv").join("Scripts").join("python.exe");
    let python = if venv_python.exists() {
        venv_python.to_string_lossy().to_string()
    } else {
        "python".to_string()
    };
    let mut cmd = Command::new(python);
    cmd.arg("main.py")
        .current_dir(&backend_dir)
        .env("ELARA_TOKEN", token);
    Some(cmd)
}

fn spawn_backend(token: &str) -> Option<Child> {
    let mut cmd = backend_command(token)?;

    #[cfg(target_os = "windows")]
    cmd.creation_flags(CREATE_NO_WINDOW);

    match cmd.spawn() {
        Ok(child) => {
            println!("[elara] backend started (pid {})", child.id());
            // Ensure it dies with us however we exit, not just on a clean quit.
            #[cfg(target_os = "windows")]
            job::bind(&child);
            Some(child)
        }
        Err(e) => {
            eprintln!("[elara] failed to start backend: {e}");
            None
        }
    }
}

fn show_main(app: &tauri::AppHandle) {
    if let Some(win) = app.get_webview_window("main") {
        let _ = win.show();
        let _ = win.unminimize();
        let _ = win.set_focus();
    }
}

#[tauri::command]
fn backend_running(state: State<Backend>) -> bool {
    let mut guard = state.0.lock().unwrap();
    match guard.as_mut() {
        Some(child) => matches!(child.try_wait(), Ok(None)),
        None => false,
    }
}

/// The webview calls this to learn the token it must present when opening the
/// backend WebSocket. Only code running inside this app can reach it.
#[tauri::command]
fn backend_token(state: State<BackendToken>) -> String {
    state.0.clone()
}

/// Fully quit: kill the backend, then exit. Called from the tray "Quit" item.
#[tauri::command]
fn quit_app(app: tauri::AppHandle) {
    if let Some(state) = app.try_state::<Backend>() {
        if let Some(mut child) = state.0.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
    app.exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let token = generate_token();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .manage(Backend(Mutex::new(None)))
        .manage(BackendToken(token.clone()))
        .setup(move |app| {
            // Start the Python mind, handing it this launch's auth token.
            let child = spawn_backend(&token);
            app.state::<Backend>()
                .0
                .lock()
                .unwrap()
                .replace(child.expect("backend must start; is Python installed?"));

            // System tray: click to show, right-click menu to show/quit.
            #[cfg(desktop)]
            {
                let show_i = MenuItem::with_id(app, "show", "Show Elara", true, None::<&str>)?;
                let quit_i = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
                let menu = Menu::with_items(app, &[&show_i, &quit_i])?;

                TrayIconBuilder::with_id("elara-tray")
                    .icon(app.default_window_icon().unwrap().clone())
                    .tooltip("Elara")
                    .menu(&menu)
                    .show_menu_on_left_click(false)
                    .on_menu_event(|app, event| match event.id.as_ref() {
                        "show" => show_main(app),
                        "quit" => {
                            if let Some(state) = app.try_state::<Backend>() {
                                if let Some(mut child) = state.0.lock().unwrap().take() {
                                    let _ = child.kill();
                                }
                            }
                            app.exit(0);
                        }
                        _ => {}
                    })
                    .on_tray_icon_event(|tray, event| {
                        if let TrayIconEvent::Click {
                            button: MouseButton::Left,
                            button_state: MouseButtonState::Up,
                            ..
                        } = event
                        {
                            show_main(tray.app_handle());
                        }
                    })
                    .build(app)?;
            }

            // Autostart on login (disabled by default; toggled from settings).
            #[cfg(desktop)]
            {
                use tauri_plugin_autostart::MacosLauncher;
                app.handle().plugin(tauri_plugin_autostart::init(
                    MacosLauncher::LaunchAgent,
                    None,
                ))?;
            }

            // Global hotkey (Ctrl+Alt+E) to bring Elara to the front.
            #[cfg(desktop)]
            {
                use tauri_plugin_global_shortcut::{
                    Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState,
                };

                let summon = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::ALT), Code::KeyE);
                let handle = app.handle().clone();
                app.handle().plugin(
                    tauri_plugin_global_shortcut::Builder::new()
                        .with_handler(move |_app, shortcut, event| {
                            if event.state == ShortcutState::Pressed && shortcut == &summon {
                                show_main(&handle);
                            }
                        })
                        .build(),
                )?;
                let _ = app.global_shortcut().register(summon);
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the window hides Elara to the tray instead of quitting.
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            backend_running,
            quit_app,
            backend_token
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
