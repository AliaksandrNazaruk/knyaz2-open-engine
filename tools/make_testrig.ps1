# Собирает запускаемое зеркало игры с установленным модом,
# не трогая оригинал в Program Files и не требуя прав администратора.
#
#   * подкаталоги (KONUNG2, PICS, VIDEO) подключаются junction'ами —
#     это ~570 МБ озвучки и видео, которые копировать незачем;
#   * корневые файлы копируются (~200 МБ), файлы мода берутся из build\.
#
#   powershell -File tools\make_testrig.ps1

param(
    [string]$Game = "C:\Program Files (x86)\Князь - Коллекционное издание\02. Князь 2 - Кровь Титанов",
    [string]$Build = "$env:USERPROFILE\Documents\Knyaz2Modding\build",
    [string]$Dest = "$env:USERPROFILE\Documents\Knyaz2Test"
)

# запущенная игра держит konung2.exe и не даёт пересобрать зеркало
Get-Process konung2 -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

if (Test-Path $Dest) {
    # junction'ы удаляем как ссылки, иначе Remove-Item пойдёт вглубь оригинала
    Get-ChildItem $Dest -Directory -Force | ForEach-Object {
        if ($_.LinkType) { [System.IO.Directory]::Delete($_.FullName) }
    }
    Remove-Item -Recurse -Force $Dest
}
New-Item -ItemType Directory -Force -Path $Dest | Out-Null

$modded = @{}
Get-ChildItem -File $Build | ForEach-Object { $modded[$_.Name] = $_.FullName }

$fromMod = 0; $fromGame = 0
Get-ChildItem -File $Game | ForEach-Object {
    $out = Join-Path $Dest $_.Name
    if ($modded.ContainsKey($_.Name)) {
        Copy-Item $modded[$_.Name] $out; $fromMod++
    } else {
        Copy-Item $_.FullName $out; $fromGame++
    }
}
Get-ChildItem -Directory $Game | ForEach-Object {
    New-Item -ItemType Junction -Path (Join-Path $Dest $_.Name) -Target $_.FullName | Out-Null
}

Write-Host "зеркало: $Dest"
Write-Host "  файлов из build\: $fromMod, из игры: $fromGame, подкаталогов подключено ссылками: $((Get-ChildItem -Directory $Game).Count)"

# Проверка инварианта: изменёнными должны быть ровно те файлы, что отличаются
# от оригинала, а сам оригинал остаться нетронутым.
$changed = @()
foreach ($name in $modded.Keys) {
    $orig = Join-Path $Game $name
    if (Test-Path $orig) {
        $a = (Get-FileHash $orig -Algorithm MD5).Hash
        $b = (Get-FileHash (Join-Path $Dest $name) -Algorithm MD5).Hash
        if ($a -ne $b) { $changed += $name }
    }
}
Write-Host "  отличаются от оригинала ($($changed.Count)):"
$changed | Sort-Object | ForEach-Object { Write-Host "    $_" }

# оригинал должен быть доступен только на чтение — проверим, что мы в него не писали
$origWrite = (Get-ChildItem -File $Game | Where-Object { $_.LastWriteTime -gt (Get-Date).AddHours(-2) }).Count
if ($origWrite -eq 0) { Write-Host "  оригинал игры не изменялся" }
else { Write-Host "  ВНИМАНИЕ: в оригинале игры $origWrite свежих файлов!" }

