"""Parsing Steam's library metadata — pure text fixtures, no Steam needed."""

from pathlib import Path

from backend.tools.steam import parse_library_paths, parse_manifest

VDF = r'''
"libraryfolders"
{
	"0"
	{
		"path"		"C:\\Program Files (x86)\\Steam"
		"label"		""
		"totalsize"		"0"
	}
	"1"
	{
		"path"		"D:\\SteamLibrary"
		"label"		""
	}
}
'''

ACF = r'''
"AppState"
{
	"appid"		"2767030"
	"universe"		"1"
	"name"		"Marvel Rivals"
	"StateFlags"		"4"
	"installdir"		"MarvelRivals"
}
'''


def test_parse_library_paths_unescapes_backslashes():
    paths = parse_library_paths(VDF)
    assert paths == [
        Path(r"C:\Program Files (x86)\Steam"),
        Path(r"D:\SteamLibrary"),
    ]


def test_parse_manifest_extracts_appid_and_name():
    assert parse_manifest(ACF) == ("2767030", "Marvel Rivals")


def test_parse_manifest_rejects_garbage():
    assert parse_manifest("not a manifest at all") is None
