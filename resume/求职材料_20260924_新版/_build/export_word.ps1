$ErrorActionPreference = 'Stop'
$baseDir = Split-Path -Parent $PSScriptRoot
$word = New-Object -ComObject Word.Application
$owned = $word.Documents.Count -eq 0
if (-not $owned) { throw 'Word automation instance contains open documents; left untouched.' }
try {
    $word.Visible = $false
    $word.DisplayAlerts = 0
    foreach ($file in Get-ChildItem -LiteralPath $baseDir -Filter '*.docx') {
        $document = $null
        try {
            $document = $word.Documents.Open($file.FullName, $false, $true, $false)
            $document.Repaginate()
            if ($file.BaseName.StartsWith('01_') -or $file.BaseName.StartsWith('02_')) {
                $pdfPath = [IO.Path]::ChangeExtension($file.FullName, '.pdf')
            } else {
                $pdfPath = Join-Path ($baseDir + '\_qa') ($file.BaseName + '.pdf')
            }
            $document.ExportAsFixedFormat($pdfPath, 17)
            Write-Output ($file.Name + ' pages=' + $document.ComputeStatistics(2))
        } finally { if ($null -ne $document) { $document.Close(0) } }
    }
} finally { if ($owned) { $word.Quit(0) }; [Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null }
