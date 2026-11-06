
$ErrorActionPreference = "Continue"

$Root = (Get-Location).Path
$ExpectedRoot = "G:\youtube automation"

if ($Root -ne $ExpectedRoot) {
    Write-Host "ERROR: Wrong project directory: $Root" -ForegroundColor Red
    exit 1
}

$ReportDir = Join-Path $Root "reports"
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

$Report = Join-Path $ReportDir "finalization_inventory_v1.txt"
$Lines = [System.Collections.Generic.List[string]]::new()

function Add-Line([string]$Text = "") {
    $Lines.Add($Text)
}

function Add-Section([string]$Name) {
    Add-Line ""
    Add-Line ("=" * 75)
    Add-Line($Name)
    Add-Line ("=" * 75)
}

function Run-Command([string]$Name, [string]$Command) {
    Add-Line ""
    Add-Line("[$Name]")
    try {
        $Result = Invoke-Expression $Command 2>&1
        foreach ($Item in $Result) {
            Add-Line([string]$Item)
        }
    }
    catch {
        Add-Line("UNAVAILABLE: " + $_.Exception.Message)
    }
}

Add-Line "YOUTUBE AUTOMATION V3.4 - READ ONLY INVENTORY"
Add-Line "Generated: $(Get-Date -Format o)"
Add-Line "Project root: $Root"
Add-Line "This audit does not run workflows, render videos, or upload content."

Add-Section "1. SYSTEM ENVIRONMENT"

Run-Command "Python" "python --version"
Run-Command "Python launcher" "py --version"
Run-Command "FFmpeg" "ffmpeg -version | Select-Object -First 1"
Run-Command "Git" "git --version"
Run-Command "Docker" "docker --version"
Run-Command "Docker containers" "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

Add-Section "2. PROJECT DIRECTORY STRUCTURE"

$TopFolders = Get-ChildItem $Root -Directory -Force |
    Where-Object { $_.Name -notin @(".venv", "node_modules", "__pycache__") }

foreach ($Folder in $TopFolders) {
    Add-Line ("DIRECTORY: " + $Folder.Name)
}

Add-Section "3. APPLICATION AND WORKFLOW FILES"

$Files = Get-ChildItem $Root -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object {
        $_.FullName -notmatch '\\(\.venv|node_modules|__pycache__|\.git|backups)\\' -and
        $_.Extension -in @(".py", ".bat", ".ps1", ".json", ".yml", ".yaml", ".toml", ".txt")
    } |
    Sort-Object FullName

foreach ($File in $Files) {
    $Relative = $File.FullName.Substring($Root.Length).TrimStart("\")
    Add-Line ("{0} | {1:N0} bytes" -f $Relative, $File.Length)
}

Add-Line ""
Add-Line "TOTAL CODE/CONFIG FILES: $($Files.Count)"

Add-Section "4. ENVIRONMENT FILE PRESENCE - NO SECRET VALUES READ"

$EnvFiles = Get-ChildItem $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
    Where-Object {
        $_.Name -in @(".env", ".env.example", ".env.template")
    } |
    Where-Object {
        $_.FullName -notmatch '\\(\.venv|node_modules|backups)\\'
    }

if ($EnvFiles.Count -eq 0) {
    Add-Line "No environment files found."
}
else {
    foreach ($File in $EnvFiles) {
        Add-Line ("PRESENT: " + $File.FullName.Substring($Root.Length).TrimStart("\"))
    }
}

Add-Line "IMPORTANT: Environment file contents and credentials were not read."

Add-Section "5. DATABASE AND APPROVED OUTPUT PRESENCE"

$ImportantPaths = @(
    "data\research\youtube_universe_v33\youtube_universe.db",
    "data\research\youtube_universe_v33\human_review_decisions_v33.csv",
    "data\research\youtube_universe_v33\research_review_decisions_v33.csv",
    "data\research\youtube_universe_v33\automated_approval_decisions_v1.csv",
    "data\research\youtube_universe_v33\latest_automated_approval_report_v1.json",
    "output\youtube_landscape_final.mp4",
    "output\short_vertical_final.mp4",
    "output\qa_reports\latest_qa_report.json"
)

foreach ($Relative in $ImportantPaths) {
    $Full = Join-Path $Root $Relative
    if (Test-Path $Full -PathType Leaf) {
        $Item = Get-Item $Full
        Add-Line ("PRESENT | {0} | {1:N0} bytes" -f $Relative, $Item.Length)
    }
    else {
        Add-Line ("NOT FOUND | " + $Relative)
    }
}

Add-Section "6. IMPORTANT CSV DATA SUMMARY"

$CsvPaths = @(
    "data\research\youtube_universe_v33\human_review_decisions_v33.csv",
    "data\research\youtube_universe_v33\research_review_decisions_v33.csv",
    "data\research\youtube_universe_v33\automated_approval_decisions_v1.csv",
    "data\research\youtube_universe_v33\latest_candidate_ranking_v33.csv",
    "data\research\youtube_universe_v33\latest_master_scored_videos_v33.csv",
    "data\research\youtube_universe_v33\latest_final_audit_v33.csv",
    "data\research\youtube_universe_v33\latest_master_dashboard_v33.csv"
)

foreach ($Relative in $CsvPaths) {
    $Full = Join-Path $Root $Relative
    if (Test-Path $Full -PathType Leaf) {
        try {
            $Rows = @(Import-Csv $Full)
            Add-Line ""
            Add-Line("FILE: " + $Relative)
            Add-Line("ROWS: " + $Rows.Count)
            if ($Rows.Count -gt 0) {
                Add-Line("COLUMNS: " + (($Rows[0].PSObject.Properties.Name) -join ", "))
            }
        }
        catch {
            Add-Line("CSV READ ERROR: $Relative : $($_.Exception.Message)")
        }
    }
    else {
        Add-Line("NOT FOUND: " + $Relative)
    }
}

Add-Section "7. RESEARCH WORKSPACE SUMMARY"

$Workspace = Join-Path $Root "data\research\youtube_universe_v33\research_workspace_v33"

if (Test-Path $Workspace) {
    $ResearchFolders = Get-ChildItem $Workspace -Directory -ErrorAction SilentlyContinue

    Add-Line("VIDEO WORKSPACES: " + $ResearchFolders.Count)

    foreach ($Folder in $ResearchFolders) {
        $SourceFile = Join-Path $Folder.FullName "sources.csv"
        $ClaimFile = Join-Path $Folder.FullName "claims.csv"
        $EvidenceFile = Join-Path $Folder.FullName "evidence.csv"

        $Counts = @()
        foreach ($Path in @($SourceFile, $ClaimFile, $EvidenceFile)) {
            if (Test-Path $Path) {
                $Count = @(Import-Csv $Path).Count
                $Counts += "$([IO.Path]::GetFileName($Path))=$Count"
            }
            else {
                $Counts += "$([IO.Path]::GetFileName($Path))=MISSING"
            }
        }

        Add-Line("$($Folder.Name) | " + ($Counts -join " | "))
    }
}
else {
    Add-Line "Research workspace not found."
}

Add-Section "8. PRODUCTION ASSETS AND OUTPUTS"

foreach ($Relative in @("production", "assets", "output", "workflows", "tests", "reports", "logs")) {
    $Full = Join-Path $Root $Relative

    if (Test-Path $Full) {
        $Items = @(Get-ChildItem $Full -Recurse -File -ErrorAction SilentlyContinue)
        $TotalBytes = ($Items | Measure-Object Length -Sum).Sum
        if ($null -eq $TotalBytes) { $TotalBytes = 0 }

        Add-Line("$Relative | FILES=$($Items.Count) | BYTES=$TotalBytes")
    }
    else {
        Add-Line("$Relative | NOT FOUND")
    }
}

Add-Section "9. PYTHON DEPENDENCY SNAPSHOT"

Run-Command "Installed packages" "python -m pip list --format=freeze"

Add-Section "10. GIT STATUS"

Push-Location $Root
try {
    Run-Command "Git repository status" "git status --short --branch"
}
finally {
    Pop-Location
}

Add-Section "11. INVENTORY SAFETY DECLARATION"

Add-Line "Database writes: NONE"
Add-Line "CSV writes: NONE"
Add-Line "Production rendering: NOT STARTED"
Add-Line "YouTube API calls: NONE"
Add-Line "Uploads: NONE"
Add-Line "Credentials displayed: NONE"
Add-Line "Inventory completed: $(Get-Date -Format o)"

[System.IO.File]::WriteAllLines(
    $Report,
    $Lines,
    [System.Text.UTF8Encoding]::new($true)
)

Write-Host ""
Write-Host "INVENTORY COMPLETED" -ForegroundColor Green
Write-Host "Report: $Report"
Write-Host "Files inspected: $($Files.Count)"
Write-Host "No production or publishing action was performed."
