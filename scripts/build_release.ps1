[CmdletBinding()]
param(
    [switch]$SkipTests,
    [switch]$SkipInstaller
)
$ErrorActionPreference = 'Stop'
function Sign-ReleaseFile([string]$File) {
    if (-not $env:SIGNING_CERT) { return }
    # SIGNING_CERT is a certificate thumbprint in the current user's Personal store.
    # Private keys remain in the Windows certificate store, never in this repository.
    $thumbprint = $env:SIGNING_CERT.Replace(' ', '')
    if ($thumbprint -notmatch '^[0-9A-Fa-f]{40}$') { throw 'SIGNING_CERT 必須是憑證 thumbprint。' }
    $cert = Get-Item -LiteralPath ("Cert:\CurrentUser\My\" + $thumbprint)
    if (-not $cert.HasPrivateKey) { throw '簽章憑證沒有可用私鑰。' }
    $result = Set-AuthenticodeSignature -FilePath $File -Certificate $cert -HashAlgorithm SHA256
    if ($result.Status -ne 'Valid') { throw "簽章失敗：$($result.Status)" }
    if ((Get-AuthenticodeSignature -FilePath $File).Status -ne 'Valid') { throw '簽章驗證失敗。' }
    $signTool = (Get-Command signtool.exe -ErrorAction SilentlyContinue).Source
    if (-not $signTool) {
        $sdkBin = Join-Path ${env:ProgramFiles(x86)} 'Windows Kits\10\bin'
        $signTool = Get-ChildItem -LiteralPath $sdkBin -Filter signtool.exe -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -match '\\x64\\signtool\.exe$' } |
            Sort-Object FullName -Descending | Select-Object -First 1 -ExpandProperty FullName
    }
    if (-not $signTool) { throw '已要求簽章，但找不到 Windows SDK signtool.exe 可供驗證。' }
    & $signTool verify /pa /v $File
    if ($LASTEXITCODE) { throw "signtool 驗證失敗：$File" }
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$PyInstaller = Join-Path $ProjectRoot '.venv\Scripts\pyinstaller.exe'
if (-not (Test-Path -LiteralPath $Python)) { throw '找不到 .venv Python。' }
$BuildNumber = [Environment]::OSVersion.Version.Build
if ($BuildNumber -lt 20348) { throw "Windows Build $BuildNumber 不支援 Process Loopback；需要 20348 或更新版本。" }
$VersionLine = Get-Content -LiteralPath (Join-Path $ProjectRoot 'src\vlt\version.py') | Where-Object { $_ -match '^__version__' }
$Version = [regex]::Match($VersionLine, '"([0-9]+\.[0-9]+\.[0-9]+)"').Groups[1].Value
if (-not $Version) { throw '無法讀取產品版本。' }

Set-Location -LiteralPath $ProjectRoot
if (-not $SkipTests) { & $Python -m pytest -q; if ($LASTEXITCODE) { throw '測試失敗。' } }
foreach ($name in @('build', 'dist', 'release')) {
    $target = Join-Path $ProjectRoot $name
    if (Test-Path -LiteralPath $target) {
        $resolved = (Resolve-Path -LiteralPath $target).Path
        if (-not $resolved.StartsWith($ProjectRoot, [StringComparison]::OrdinalIgnoreCase)) { throw "拒絕清除工作區外路徑：$resolved" }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
New-Item -ItemType Directory -Path (Join-Path $ProjectRoot 'release') | Out-Null
$VersionParts = $Version.Split('.') | ForEach-Object { [int]$_ }
$VersionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(filevers=($($VersionParts[0]),$($VersionParts[1]),$($VersionParts[2]),0), prodvers=($($VersionParts[0]),$($VersionParts[1]),$($VersionParts[2]),0), mask=0x3f, flags=0x0,
    OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)),
  kids=[StringFileInfo([StringTable('040904B0', [
    StringStruct('CompanyName', 'Vtuber Live Translator'),
    StringStruct('FileDescription', 'Vtuber Live Translator'),
    StringStruct('FileVersion', '$Version'),
    StringStruct('InternalName', 'VtuberLiveTranslator'),
    StringStruct('OriginalFilename', 'VtuberLiveTranslator.exe'),
    StringStruct('ProductName', 'Vtuber Live Translator'),
    StringStruct('ProductVersion', '$Version')])]), VarFileInfo([VarStruct('Translation', [1033,1200])])])
"@
[IO.File]::WriteAllText((Join-Path $ProjectRoot 'packaging\version_info.txt'), $VersionInfo,
                        [Text.UTF8Encoding]::new($false))
& $PyInstaller --noconfirm --clean (Join-Path $ProjectRoot 'packaging\VtuberLiveTranslator.spec')
if ($LASTEXITCODE) { throw 'EXE 建置失敗。' }
$AppExe = Join-Path $ProjectRoot 'dist\VtuberLiveTranslator\VtuberLiveTranslator.exe'
Sign-ReleaseFile $AppExe
Copy-Item -LiteralPath (Join-Path $ProjectRoot 'dist\VtuberLiveTranslator') -Destination (Join-Path $ProjectRoot 'release\VtuberLiveTranslator') -Recurse

if (-not $SkipInstaller) {
    $Iscc = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
    if (-not (Test-Path -LiteralPath $Iscc)) { $Iscc = (Get-Command iscc.exe -ErrorAction Stop).Source }
    & $Iscc "/DMyAppVersion=$Version" (Join-Path $ProjectRoot 'installer\VtuberLiveTranslator.iss')
    if ($LASTEXITCODE) { throw 'Installer 建置失敗。' }
    $Installer = Join-Path $ProjectRoot 'installer\output\VtuberLiveTranslator-Setup.exe'
    Sign-ReleaseFile $Installer
    Copy-Item -LiteralPath $Installer -Destination (Join-Path $ProjectRoot "release\VtuberLiveTranslator-$Version-Setup.exe")
}
Copy-Item -LiteralPath (Join-Path $ProjectRoot "RELEASE_NOTES_$Version.md") -Destination (Join-Path $ProjectRoot 'release')
$HashTargets = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'release') -File)
$HashTargets += Get-Item -LiteralPath (Join-Path $ProjectRoot 'release\VtuberLiveTranslator\VtuberLiveTranslator.exe')
$HashTargets | ForEach-Object {
    $hash = Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256
    $relative = $_.FullName.Substring((Join-Path $ProjectRoot 'release').Length + 1).Replace('\', '/')
    "$($hash.Hash.ToLower())  $relative"
} | Set-Content -LiteralPath (Join-Path $ProjectRoot 'release\SHA256SUMS.txt') -Encoding ascii
Write-Host "Vtuber Live Translator $Version release ready: $(Join-Path $ProjectRoot 'release')"
