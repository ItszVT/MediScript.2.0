# One-shot GitHub setup for MediScript (Windows PowerShell).
#   .\scripts\setup_github.ps1 -Repo mediscript [-Private]
param([string]$Repo = "mediscript", [switch]$Private)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".git")) { git init -q }
git add -A
git commit -qm "Initial commit: MediScript prescription reader + pharmacy platform" 2>$null
git branch -M main

$vis = if ($Private) { "private" } else { "public" }
if (Get-Command gh -ErrorAction SilentlyContinue) {
    Write-Host "Creating $vis GitHub repo '$Repo' and pushing..."
    gh repo create $Repo --$vis --source=. --remote=origin --push
    Write-Host "Done."
} else {
    Write-Host "GitHub CLI (gh) not found. Local commit is ready. To finish:"
    Write-Host "  1) Create an empty repo named '$Repo' on github.com (no README)."
    Write-Host "  2) Run:"
    Write-Host "       git remote add origin https://github.com/<you>/$Repo.git"
    Write-Host "       git push -u origin main"
}
