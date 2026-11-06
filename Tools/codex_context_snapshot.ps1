param(
    [string]$RepoRoot = "D:\YT-Visuals"
)

$ErrorActionPreference = "Stop"
Set-Location $RepoRoot

$outDir = Join-Path $RepoRoot "docs\codex"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$outFile = Join-Path $outDir "PHASE9_CONTEXT.md"
$fence = '```'

function Add-Section([string]$Title, [scriptblock]$Body) {
    Add-Content -Path $outFile -Value "`n## $Title`n"
    try {
        $v = (& $Body 2>&1 | Out-String)
        if ($v.Length -gt 16000) {
            $v = $v.Substring(0, 16000) + "`n[truncated]"
        }
        $payload = $fence + "text`n" + $v + $fence
        Add-Content -Path $outFile -Value $payload
    }
    catch {
        $payload = $fence + "text`nERROR: " + $_.Exception.Message + "`n" + $fence
        Add-Content -Path $outFile -Value $payload
    }
}

Set-Content -Path $outFile -Value "# Phase 9 Repository Context Snapshot`n`nGenerated: $(Get-Date -Format o)`nRepo: $RepoRoot"

Add-Section "Git" {
    git rev-parse --show-toplevel
    git rev-parse HEAD
    git status --short
    git log -5 --oneline
}

Add-Section "Top-level layout" {
    Get-ChildItem -Force | Select-Object Mode,Length,LastWriteTime,Name | Format-Table -AutoSize
}

Add-Section "Relevant source files" {
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        rg --files | rg "(story|visual|plan|release|artifact|document|timeline|production|route|web|workflow|migration|alembic|test)" | Select-Object -First 300
    }
    else {
        Get-ChildItem -Recurse -File |
            Where-Object { $_.FullName -match '(story|visual|plan|release|artifact|document|timeline|production|route|web|workflow|migration|alembic|test)' } |
            Select-Object -First 300 -ExpandProperty FullName
    }
}

Add-Section "Key symbols and routes" {
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        rg -n --glob '!*.lock' --glob '!*.min.*' --glob '!node_modules/**' --glob '!.venv/**' "StoryWorkspace|VisualPlan|ProductionEvent|StoryDocumentVersion|ReleaseProductionArtifact|MediaAsset|story_id|visual_plan|open folder|Open Folder|download.*zip|send_file|FileResponse" . |
            Select-Object -First 500
    }
    else {
        "rg not installed; skip symbol snapshot"
    }
}

Add-Section "Migrations" {
    Get-ChildItem -Recurse -File |
        Where-Object { $_.FullName -match '(alembic|migration|versions)' } |
        Sort-Object FullName |
        Select-Object -First 250 -ExpandProperty FullName
}

Add-Section "Alembic heads" {
    $py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $py) {
        & $py -m alembic heads
    }
    else {
        "Python venv not found at $py"
    }
}

Add-Section "SQLite schema summary" {
    $py = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    $db = Join-Path $RepoRoot "Data\catalog.sqlite3"
    if ((Test-Path $py) -and (Test-Path $db)) {
        $code = @'
import sqlite3, sys
p = sys.argv[1]
cx = sqlite3.connect(p)
for name, sql in cx.execute("select name, sql from sqlite_master where type='table' and name not like 'sqlite_%' order by name"):
    print(f"\nTABLE {name}")
    print(sql or "")
    fks = list(cx.execute(f"pragma foreign_key_list('{name}')"))
    if fks:
        print("FOREIGN KEYS:")
        for fk in fks:
            print(fk)
cx.close()
'@
        $code | & $py - $db
    }
    else {
        "DB or venv missing; schema summary skipped"
    }
}

Add-Section "Focused tests inventory" {
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        rg --files | rg '(^|/|\\)test.*\.py$|.*_test\.py$' | Select-Object -First 400
    }
    else {
        Get-ChildItem -Recurse -File -Filter "test*.py" | Select-Object -First 400 -ExpandProperty FullName
    }
}

Add-Section "Storage/path assumptions" {
    if (Get-Command rg -ErrorAction SilentlyContinue) {
        rg -n --glob '!.venv/**' --glob '!node_modules/**' "Projects|Releases|Library|Temp|/projects|/releases|/library|/temp|catalog.sqlite3|workspace_root|storage_root|relative_path|absolute_path" . |
            Select-Object -First 500
    }
    else {
        "rg not installed; skip path snapshot"
    }
}

Write-Host "Wrote $outFile"
