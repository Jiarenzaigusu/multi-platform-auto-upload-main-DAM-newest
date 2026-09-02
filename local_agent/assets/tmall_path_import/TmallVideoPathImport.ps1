Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.IO.Compression.FileSystem
$ErrorActionPreference = "Stop"

function PickFolder([string]$description) {
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = $description
    if ($dialog.ShowDialog() -ne "OK") { throw "操作已取消。" }
    return $dialog.SelectedPath
}

function PickFile([string]$description) {
    $dialog = New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Title = $description
    $dialog.Filter = "Excel 工作簿 (*.xlsx)|*.xlsx"
    $dialog.InitialDirectory = $PSScriptRoot
    if ($dialog.ShowDialog() -ne "OK") { throw "操作已取消。" }
    return $dialog.FileName
}

function PickOutput([string]$directory, [string]$defaultName) {
    $dialog = New-Object System.Windows.Forms.SaveFileDialog
    $dialog.Title = "选择输出工作簿"
    $dialog.Filter = "Excel 工作簿 (*.xlsx)|*.xlsx"
    $dialog.InitialDirectory = $directory
    $dialog.FileName = $defaultName
    if ($dialog.ShowDialog() -ne "OK") { throw "操作已取消。" }
    return $dialog.FileName
}

function Stem($file) {
    return $file.BaseName.Trim().Normalize([Text.NormalizationForm]::FormKC).ToLowerInvariant()
}

function SetCell($document, [string]$reference, [string]$value) {
    $cell = $document.SelectSingleNode("//*[local-name()='c' and @r='$reference']")
    if ($null -eq $cell) {
        $rowNumber = [regex]::Match($reference, '\d+').Value
        $row = $document.SelectSingleNode("//*[local-name()='row' and @r='$rowNumber']")
        $cell = $document.CreateElement("c", $document.DocumentElement.NamespaceURI)
        $cell.SetAttribute("r", $reference)
        $column = [regex]::Match($reference, '^[A-Z]+').Value
        $before = $null
        foreach ($existing in $row.SelectNodes("*[local-name()='c']")) {
            $existingColumn = [regex]::Match($existing.GetAttribute("r"), '^[A-Z]+').Value
            if ([String]::CompareOrdinal($existingColumn, $column) -gt 0) {
                $before = $existing
                break
            }
        }
        if ($null -eq $before) { $row.AppendChild($cell) | Out-Null }
        else { $row.InsertBefore($cell, $before) | Out-Null }
    }
    while ($cell.HasChildNodes) { $cell.RemoveChild($cell.FirstChild) | Out-Null }
    if ([String]::IsNullOrEmpty($value)) { return }
    $cell.SetAttribute("t", "inlineStr")
    $inline = $document.CreateElement("is", $document.DocumentElement.NamespaceURI)
    $text = $document.CreateElement("t", $document.DocumentElement.NamespaceURI)
    $text.InnerText = $value
    $inline.AppendChild($text) | Out-Null
    $cell.AppendChild($inline) | Out-Null
}

$temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) ("mpau_path_import_" + [guid]::NewGuid().ToString("N"))
try {
    $template = PickFile "第 1 步：选择天猫或京东的视频/图文模板"
    $archive = [IO.Compression.ZipFile]::OpenRead($template)
    try {
        $entry = $archive.GetEntry("xl/worksheets/sheet1.xml")
        if ($null -eq $entry) { throw "模板缺少第一个工作表。" }
        $reader = New-Object IO.StreamReader($entry.Open(), [Text.Encoding]::UTF8)
        try { $sheetXml = $reader.ReadToEnd() } finally { $reader.Dispose() }
    } finally { $archive.Dispose() }

    $isImage = $sheetXml.Contains("图片文件夹路径")
    $isVideo = $sheetXml.Contains("视频路径")
    if (-not $isImage -and -not $isVideo) { throw "无法识别模板：缺少“视频路径”或“图片文件夹路径”表头。" }
    $isJd = $sheetXml.Contains("自主原创")
    $platformLabel = if ($isJd) { "京东" } else { "天猫" }
    $contentLabel = if ($isImage) { "图文" } else { "视频" }

    $source = PickFolder $(if ($isImage) { "第 2 步：选择包含图文任务文件夹的总文件夹" } else { "第 2 步：选择视频文件夹" })
    $cover = $null
    if ($isVideo) {
        $useCover = [Windows.Forms.MessageBox]::Show("是否按同名文件导入封面？", "可选封面", "YesNo", "Question")
        if ($useCover -eq "Yes") { $cover = PickFolder "第 3 步：选择封面文件夹" }
    }
    $output = PickOutput (Split-Path $template) "${platformLabel}_${contentLabel}_已导入.xlsx"
    if ([String]::Equals($template, $output, [StringComparison]::OrdinalIgnoreCase)) { throw "输出文件不能覆盖模板。" }

    $videoExtensions = @(".mp4", ".mov", ".avi", ".mkv", ".wmv", ".flv", ".m4v", ".webm")
    $files = if ($isImage) {
        @(Get-ChildItem -LiteralPath $source -Directory | Sort-Object Name)
    } else {
        @(Get-ChildItem -LiteralPath $source -File -Recurse | Where-Object { $videoExtensions -contains $_.Extension.ToLowerInvariant() } | Sort-Object FullName)
    }
    if ($files.Count -eq 0) { throw "没有找到支持的文件。" }
    if ($files.Count -gt 200) { throw "模板最多支持 200 行。" }

    $coverMap = @{}
    if ($null -ne $cover) {
        foreach ($file in @(Get-ChildItem -LiteralPath $cover -File -Recurse)) {
            $key = Stem $file
            if (-not $coverMap.ContainsKey($key)) { $coverMap[$key] = $file.FullName }
        }
    }

    New-Item -ItemType Directory $temporaryDirectory | Out-Null
    [IO.Compression.ZipFile]::ExtractToDirectory($template, $temporaryDirectory)
    $sheetPath = Join-Path $temporaryDirectory "xl\worksheets\sheet1.xml"
    $document = New-Object Xml.XmlDocument
    $document.PreserveWhitespace = $true
    $document.Load($sheetPath)
    foreach ($rowNumber in 2..201) {
        foreach ($column in @("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K")) {
            SetCell $document "${column}${rowNumber}" ""
        }
    }
    $missingCovers = 0
    for ($index = 0; $index -lt $files.Count; $index++) {
        $rowNumber = $index + 2
        SetCell $document "A$rowNumber" $files[$index].FullName
        if ($null -ne $cover) {
            $key = Stem $files[$index]
            if ($coverMap.ContainsKey($key)) { SetCell $document "B$rowNumber" $coverMap[$key] }
            else { $missingCovers++ }
        }
    }
    $document.Save($sheetPath)
    if (Test-Path $output) { Remove-Item $output -Force }
    [IO.Compression.ZipFile]::CreateFromDirectory($temporaryDirectory, $output)

    $message = "完成（${platformLabel}${contentLabel}模板）。`r`n文件数量：$($files.Count)"
    if ($null -ne $cover) {
        $message += "`r`n已匹配封面：$($files.Count - $missingCovers)`r`n未匹配视频：$missingCovers"
    } elseif ($isVideo) { $message += "`r`n封面：已跳过" }
    $message += "`r`n`r`n输出文件：$output"
    [Windows.Forms.MessageBox]::Show($message, "批量发布路径导入", "OK", "Information") | Out-Null
} catch {
    [Windows.Forms.MessageBox]::Show($_.Exception.Message, "导入失败", "OK", "Error") | Out-Null
    exit 1
} finally {
    if (Test-Path $temporaryDirectory) { Remove-Item $temporaryDirectory -Recurse -Force }
}
