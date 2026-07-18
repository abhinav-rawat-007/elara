import { useEffect, useState } from "react";
import { Settings2 } from "lucide-react";
import { ElaraConfig } from "@/lib/protocol";
import { getAutostart, isTauri, setAutostart } from "@/lib/tauri";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface SettingsDialogProps {
  config: ElaraConfig | null;
  onChange: (patch: Partial<ElaraConfig>) => void;
}

export function SettingsDialog({ config, onChange }: SettingsDialogProps) {
  const [autostart, setAutostartState] = useState(false);
  const inTauri = isTauri();

  useEffect(() => {
    if (inTauri) getAutostart().then(setAutostartState);
  }, [inTauri]);

  const toggleAutostart = (on: boolean) => {
    setAutostartState(on);
    void setAutostart(on);
  };

  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          title="Settings"
          aria-label="Open settings"
        >
          <Settings2 className="size-4" />
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Elara settings</DialogTitle>
          <DialogDescription>
            Tune her voice and behaviour. Changes save instantly.
          </DialogDescription>
        </DialogHeader>

        {config && (
          <div className="space-y-5 py-2">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Speak replies aloud</Label>
                <p className="text-xs text-muted-foreground">
                  Turn off for text-only mode.
                </p>
              </div>
              <Switch
                checked={config.speak_replies}
                onCheckedChange={(speak_replies) => onChange({ speak_replies })}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Speaks up on her own</Label>
                <p className="text-xs text-muted-foreground">
                  After a quiet stretch she may say something unprompted.
                </p>
              </div>
              <Switch
                checked={config.proactive}
                onCheckedChange={(proactive) => onChange({ proactive })}
              />
            </div>

            {inTauri && (
              <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                  <Label>Launch on startup</Label>
                  <p className="text-xs text-muted-foreground">
                    Start Elara automatically when you log in.
                  </p>
                </div>
                <Switch
                  checked={autostart}
                  onCheckedChange={toggleAutostart}
                />
              </div>
            )}

            <div className="space-y-2">
              <Label>What should she call you?</Label>
              <Input
                defaultValue={config.user_name}
                onBlur={(e) => onChange({ user_name: e.target.value })}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Cloud brain source</Label>
                <p className="text-xs text-muted-foreground">
                  Powers big multi-step tasks. Auto prefers your Claude
                  subscription (via Claude Code), then the API key.
                </p>
              </div>
              <Select
                value={config.cloud_backend ?? "auto"}
                onValueChange={(cloud_backend) =>
                  onChange({
                    cloud_backend: cloud_backend as ElaraConfig["cloud_backend"],
                  })
                }
              >
                <SelectTrigger className="w-36">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="subscription">Subscription</SelectItem>
                  <SelectItem value="api">API key</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-2">
              <Label>Anthropic API key (optional)</Label>
              <p className="text-xs text-muted-foreground">
                Only needed if you don't use Claude Code. Leave empty to rely
                on your subscription or stay fully local.
              </p>
              <Input
                type="password"
                placeholder="sk-ant-…"
                defaultValue={config.anthropic_api_key}
                onBlur={(e) => onChange({ anthropic_api_key: e.target.value.trim() })}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>When to use the cloud brain</Label>
                <p className="text-xs text-muted-foreground">
                  Auto: she escalates herself when a task needs it.
                </p>
              </div>
              <Select
                value={config.cloud_mode ?? "auto"}
                onValueChange={(cloud_mode) =>
                  onChange({ cloud_mode: cloud_mode as ElaraConfig["cloud_mode"] })
                }
              >
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">Auto</SelectItem>
                  <SelectItem value="always">Always</SelectItem>
                  <SelectItem value="never">Never</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="telemetry space-y-1.5 rounded-lg border border-border bg-secondary/40 p-3 text-muted-foreground">
              <div className="flex justify-between gap-4">
                <span>Brain</span>
                <span className="normal-case text-foreground/85">{config.model}</span>
              </div>
              <div className="flex justify-between gap-4">
                <span>Ears</span>
                <span className="normal-case text-foreground/85">
                  whisper {config.stt_model}
                </span>
              </div>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
