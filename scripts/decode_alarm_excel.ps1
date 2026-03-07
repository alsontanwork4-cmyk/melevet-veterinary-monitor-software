param(
    [Parameter(Mandatory = $true)]
    [string]$DataPath,

    [Parameter(Mandatory = $true)]
    [string]$IndexPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$FrameSize = 124
$IndexHeaderSize = 16
$IndexEntrySize = 16
$IndexTrailerSize = 6

function Get-AlarmCategory {
    param(
        [byte]$FlagHi,
        [byte]$FlagLo
    )

    switch ("$FlagHi,$FlagLo") {
        "1,2" { return "technical" }
        "2,3" { return "physiological_warning" }
        "3,1" { return "technical_critical" }
        "3,3" { return "physiological_critical" }
        "4,1" { return "system" }
        "4,2" { return "informational" }
        default { return "informational" }
    }
}

function Get-CleanAlarmMessage {
    param([byte[]]$Bytes)

    $zeroIndex = [Array]::IndexOf($Bytes, [byte]0)
    if ($zeroIndex -eq 0) {
        return ""
    }
    if ($zeroIndex -gt 0) {
        $Bytes = $Bytes[0..($zeroIndex - 1)]
    }

    $text = [System.Text.Encoding]::ASCII.GetString($Bytes).Trim()
    while ($text.Length -gt 0 -and -not [char]::IsLetterOrDigit($text[0]) -and "[]()".IndexOf($text[0]) -lt 0) {
        $text = $text.Substring(1)
    }
    return $text
}

function Decode-UnixSeconds {
    param(
        [uint32]$TsLo,
        [uint32]$TsHi
    )

    return [uint32](((($TsHi -band 0x0000FFFF) -shl 16) -bor ($TsLo -shr 16)))
}

function Format-Utc {
    param([uint32]$UnixSeconds)

    return [DateTimeOffset]::FromUnixTimeSeconds([int64]$UnixSeconds).UtcDateTime.ToString("yyyy-MM-dd HH:mm:ss")
}

function Format-Local {
    param(
        [uint32]$UnixSeconds,
        [System.TimeZoneInfo]$TimeZone
    )

    $utc = [DateTimeOffset]::FromUnixTimeSeconds([int64]$UnixSeconds).UtcDateTime
    return [System.TimeZoneInfo]::ConvertTimeFromUtc($utc, $TimeZone).ToString("yyyy-MM-dd HH:mm:ss")
}

function Get-ExcelColumnName {
    param([int]$ColumnNumber)

    $dividend = $ColumnNumber
    $name = ""
    while ($dividend -gt 0) {
        $modulo = ($dividend - 1) % 26
        $name = [char](65 + $modulo) + $name
        $dividend = [math]::Floor(($dividend - $modulo) / 26)
    }
    return $name
}

function Escape-Xml {
    param([string]$Text)

    if ($null -eq $Text) {
        return ""
    }
    return [System.Security.SecurityElement]::Escape([string]$Text)
}

function New-CellXml {
    param(
        [int]$ColumnNumber,
        [int]$RowNumber,
        [object]$Value
    )

    $cellRef = "{0}{1}" -f (Get-ExcelColumnName -ColumnNumber $ColumnNumber), $RowNumber
    if ($null -eq $Value -or $Value -eq "") {
        return "<c r=""$cellRef"" t=""inlineStr""><is><t></t></is></c>"
    }

    if ($Value -is [byte] -or $Value -is [int16] -or $Value -is [uint16] -or $Value -is [int32] -or $Value -is [uint32] -or $Value -is [int64] -or $Value -is [uint64] -or $Value -is [decimal] -or $Value -is [double] -or $Value -is [single]) {
        $numeric = [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, "{0}", $Value)
        return "<c r=""$cellRef""><v>$numeric</v></c>"
    }

    $escaped = Escape-Xml -Text ([string]$Value)
    $preserve = if ($escaped -match '^\s' -or $escaped -match '\s$') { ' xml:space="preserve"' } else { '' }
    return "<c r=""$cellRef"" t=""inlineStr""><is><t$preserve>$escaped</t></is></c>"
}

function Write-WorksheetXml {
    param(
        [string]$Path,
        [string[]]$Headers,
        [System.Collections.IEnumerable]$Rows
    )

    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
    [void]$sb.AppendLine('<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">')
    [void]$sb.AppendLine('<sheetData>')

    $rowNumber = 1
    [void]$sb.Append("<row r=""1"">")
    for ($i = 0; $i -lt $Headers.Count; $i++) {
        [void]$sb.Append((New-CellXml -ColumnNumber ($i + 1) -RowNumber $rowNumber -Value $Headers[$i]))
    }
    [void]$sb.AppendLine('</row>')

    foreach ($row in $Rows) {
        $rowNumber++
        [void]$sb.Append("<row r=""$rowNumber"">")
        for ($i = 0; $i -lt $Headers.Count; $i++) {
            $header = $Headers[$i]
            $value = $null
            if ($row -is [System.Collections.IDictionary]) {
                if ($row.Contains($header)) {
                    $value = $row[$header]
                }
            }
            else {
                $property = $row.PSObject.Properties[$header]
                if ($null -ne $property) {
                    $value = $property.Value
                }
            }
            [void]$sb.Append((New-CellXml -ColumnNumber ($i + 1) -RowNumber $rowNumber -Value $value))
        }
        [void]$sb.AppendLine('</row>')
    }

    [void]$sb.AppendLine('</sheetData>')
    [void]$sb.AppendLine('</worksheet>')
    [System.IO.File]::WriteAllText($Path, $sb.ToString(), [System.Text.UTF8Encoding]::new($false))
}

function Write-WorkbookPackage {
    param(
        [string]$Path,
        [hashtable[]]$Sheets
    )

    $outputDir = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($outputDir)) {
        [System.IO.Directory]::CreateDirectory($outputDir) | Out-Null
    }

    $tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("alarm-xlsx-" + [guid]::NewGuid().ToString("N"))
    $xlDir = Join-Path $tempRoot "xl"
    $worksheetsDir = Join-Path $xlDir "worksheets"
    $relsDir = Join-Path $tempRoot "_rels"
    $xlRelsDir = Join-Path $xlDir "_rels"

    [System.IO.Directory]::CreateDirectory($worksheetsDir) | Out-Null
    [System.IO.Directory]::CreateDirectory($relsDir) | Out-Null
    [System.IO.Directory]::CreateDirectory($xlRelsDir) | Out-Null

    try {
        for ($i = 0; $i -lt $Sheets.Count; $i++) {
            $sheetPath = Join-Path $worksheetsDir ("sheet{0}.xml" -f ($i + 1))
            Write-WorksheetXml -Path $sheetPath -Headers $Sheets[$i].Headers -Rows $Sheets[$i].Rows
        }

        $contentTypes = [System.Text.StringBuilder]::new()
        [void]$contentTypes.AppendLine('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
        [void]$contentTypes.AppendLine('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">')
        [void]$contentTypes.AppendLine('<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>')
        [void]$contentTypes.AppendLine('<Default Extension="xml" ContentType="application/xml"/>')
        [void]$contentTypes.AppendLine('<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>')
        for ($i = 0; $i -lt $Sheets.Count; $i++) {
            [void]$contentTypes.AppendLine('<Override PartName="/xl/worksheets/sheet{0}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' -f ($i + 1))
        }
        [void]$contentTypes.AppendLine('</Types>')
        [System.IO.File]::WriteAllText((Join-Path $tempRoot "[Content_Types].xml"), $contentTypes.ToString(), [System.Text.UTF8Encoding]::new($false))

        $rootRels = @'
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
'@
        [System.IO.File]::WriteAllText((Join-Path $relsDir ".rels"), $rootRels, [System.Text.UTF8Encoding]::new($false))

        $workbook = [System.Text.StringBuilder]::new()
        [void]$workbook.AppendLine('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
        [void]$workbook.AppendLine('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">')
        [void]$workbook.AppendLine('<sheets>')
        for ($i = 0; $i -lt $Sheets.Count; $i++) {
            $name = Escape-Xml -Text $Sheets[$i].Name
            [void]$workbook.AppendLine(('<sheet name="{0}" sheetId="{1}" r:id="rId{1}"/>' -f $name, ($i + 1)))
        }
        [void]$workbook.AppendLine('</sheets>')
        [void]$workbook.AppendLine('</workbook>')
        [System.IO.File]::WriteAllText((Join-Path $xlDir "workbook.xml"), $workbook.ToString(), [System.Text.UTF8Encoding]::new($false))

        $workbookRels = [System.Text.StringBuilder]::new()
        [void]$workbookRels.AppendLine('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>')
        [void]$workbookRels.AppendLine('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">')
        for ($i = 0; $i -lt $Sheets.Count; $i++) {
            [void]$workbookRels.AppendLine('<Relationship Id="rId{0}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{0}.xml"/>' -f ($i + 1))
        }
        [void]$workbookRels.AppendLine('</Relationships>')
        [System.IO.File]::WriteAllText((Join-Path $xlRelsDir "workbook.xml.rels"), $workbookRels.ToString(), [System.Text.UTF8Encoding]::new($false))

        if (Test-Path $Path) {
            Remove-Item -Path $Path -Force
        }
        Compress-Archive -Path (Join-Path $tempRoot '*') -DestinationPath $Path -Force
    }
    finally {
        if (Test-Path $tempRoot) {
            Remove-Item -Path $tempRoot -Recurse -Force
        }
    }
}

$dataBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $DataPath))
$indexBytes = [System.IO.File]::ReadAllBytes((Resolve-Path $IndexPath))

if ($dataBytes.Length % $FrameSize -ne 0) {
    throw "Alarm data file size is not aligned to 124-byte frames."
}
if ($indexBytes.Length -lt ($IndexHeaderSize + $IndexTrailerSize)) {
    throw "Index file is too small."
}

$payloadLength = $indexBytes.Length - $IndexHeaderSize - $IndexTrailerSize
if ($payloadLength % $IndexEntrySize -ne 0) {
    throw "Index payload is not aligned to 16-byte entries."
}

$frameCount = [int]($dataBytes.Length / $FrameSize)
$entryCount = [int]($payloadLength / $IndexEntrySize)
if ($frameCount -ne $entryCount) {
    throw "Index entries ($entryCount) do not match data frames ($frameCount)."
}

$localTimeZone = [System.TimeZoneInfo]::Local
$header = [ordered]@{
    version = [BitConverter]::ToUInt32($indexBytes, 0)
    buffer_size = [BitConverter]::ToUInt32($indexBytes, 4)
    payload_size = [BitConverter]::ToUInt32($indexBytes, 8)
    padding = [BitConverter]::ToUInt32($indexBytes, 12)
}
$trailerHex = ([BitConverter]::ToString($indexBytes[($indexBytes.Length - $IndexTrailerSize)..($indexBytes.Length - 1)])).Replace("-", "")

$alarmsRaw = New-Object System.Collections.Generic.List[object]
$indexRows = New-Object System.Collections.Generic.List[object]
$messageCounts = @{}
$categoryCounts = @{}
$rollbackIndices = New-Object System.Collections.Generic.List[int]
$previousUnix = $null
$minUnix = [uint32]::MaxValue
$maxUnix = [uint32]0

for ($i = 0; $i -lt $frameCount; $i++) {
    $frameOffset = $i * $FrameSize
    $frame = $dataBytes[$frameOffset..($frameOffset + $FrameSize - 1)]

    $flagLo = [byte]$frame[0]
    $flagHi = [byte]$frame[1]
    $alarmSubId = [byte]$frame[25]
    $message = Get-CleanAlarmMessage -Bytes $frame[26..121]
    $category = Get-AlarmCategory -FlagHi $flagHi -FlagLo $flagLo

    if ($messageCounts.ContainsKey($message)) {
        $messageCounts[$message]++
    }
    else {
        $messageCounts[$message] = 1
    }
    if ($categoryCounts.ContainsKey($category)) {
        $categoryCounts[$category]++
    }
    else {
        $categoryCounts[$category] = 1
    }

    $indexOffset = $IndexHeaderSize + ($i * $IndexEntrySize)
    $flags = [BitConverter]::ToUInt32($indexBytes, $indexOffset)
    $ptr = [BitConverter]::ToUInt32($indexBytes, $indexOffset + 4)
    $tsLo = [BitConverter]::ToUInt32($indexBytes, $indexOffset + 8)
    $tsHi = [BitConverter]::ToUInt32($indexBytes, $indexOffset + 12)
    $unixSeconds = Decode-UnixSeconds -TsLo $tsLo -TsHi $tsHi
    $timestampUtc = Format-Utc -UnixSeconds $unixSeconds
    $timestampLocal = Format-Local -UnixSeconds $unixSeconds -TimeZone $localTimeZone

    if ($null -ne $previousUnix -and $unixSeconds -lt $previousUnix) {
        $rollbackIndices.Add($i) | Out-Null
    }
    $previousUnix = $unixSeconds

    if ($unixSeconds -lt $minUnix) { $minUnix = $unixSeconds }
    if ($unixSeconds -gt $maxUnix) { $maxUnix = $unixSeconds }

    $alarmsRaw.Add([ordered]@{
        frame_index = $i
        byte_offset = $frameOffset
        timestamp_unix = [int64]$unixSeconds
        timestamp_utc = $timestampUtc
        timestamp_local = $timestampLocal
        flag_hi = [int]$flagHi
        flag_lo = [int]$flagLo
        category = $category
        alarm_sub_id = [int]$alarmSubId
        message = $message
        index_flags = [int64]$flags
        index_ptr = [int64]$ptr
        index_ts_lo = [int64]$tsLo
        index_ts_hi = [int64]$tsHi
    }) | Out-Null

    $indexRows.Add([ordered]@{
        frame_index = $i
        flags = [int64]$flags
        ptr = [int64]$ptr
        ts_lo = [int64]$tsLo
        ts_hi = [int64]$tsHi
        timestamp_unix = [int64]$unixSeconds
        timestamp_utc = $timestampUtc
        timestamp_local = $timestampLocal
    }) | Out-Null
}

$alarmsChronological = $alarmsRaw | Sort-Object @{ Expression = "timestamp_unix"; Ascending = $true }, @{ Expression = "frame_index"; Ascending = $true }
$categorySummary = $categoryCounts.GetEnumerator() | Sort-Object Value -Descending | ForEach-Object {
    [ordered]@{
        category = $_.Key
        count = $_.Value
    }
}
$messageSummary = $messageCounts.GetEnumerator() | Sort-Object @{ Expression = "Value"; Descending = $true }, @{ Expression = "Key"; Ascending = $true } | Select-Object -First 50 | ForEach-Object {
    [ordered]@{
        message = $_.Key
        count = $_.Value
    }
}

$outputDir = Split-Path -Parent $OutputPath
if ([string]::IsNullOrWhiteSpace($outputDir)) {
    $outputDir = (Get-Location).Path
}

$notesRows = @(
    [ordered]@{ field = "data_path"; value = (Resolve-Path $DataPath).Path },
    [ordered]@{ field = "index_path"; value = (Resolve-Path $IndexPath).Path },
    [ordered]@{ field = "output_directory"; value = [System.IO.Path]::GetFullPath($outputDir) },
    [ordered]@{ field = "frame_size_bytes"; value = $FrameSize },
    [ordered]@{ field = "index_header_size_bytes"; value = $IndexHeaderSize },
    [ordered]@{ field = "index_entry_size_bytes"; value = $IndexEntrySize },
    [ordered]@{ field = "index_trailer_size_bytes"; value = $IndexTrailerSize },
    [ordered]@{ field = "decoded_frame_count"; value = $frameCount },
    [ordered]@{ field = "header_version"; value = $header.version },
    [ordered]@{ field = "header_buffer_size"; value = $header.buffer_size },
    [ordered]@{ field = "header_payload_size"; value = $header.payload_size },
    [ordered]@{ field = "header_padding"; value = $header.padding },
    [ordered]@{ field = "index_trailer_hex"; value = $trailerHex },
    [ordered]@{ field = "timestamp_range_utc"; value = ("{0} to {1}" -f (Format-Utc -UnixSeconds $minUnix), (Format-Utc -UnixSeconds $maxUnix)) },
    [ordered]@{ field = "timestamp_range_local"; value = ("{0} to {1}" -f (Format-Local -UnixSeconds $minUnix -TimeZone $localTimeZone), (Format-Local -UnixSeconds $maxUnix -TimeZone $localTimeZone)) },
    [ordered]@{ field = "rollback_count"; value = $rollbackIndices.Count },
    [ordered]@{ field = "rollback_indices"; value = ($rollbackIndices -join ",") },
    [ordered]@{ field = "local_timezone_used"; value = $localTimeZone.Id },
    [ordered]@{ field = "decode_notes"; value = "Alarm categories and message offsets follow backend/app/parsers/alarm_parser.py and backend/app/parsers/index_parser.py in this workspace." }
)

$sheets = @(
    @{
        Name = "alarms_raw_order"
        Headers = @("frame_index", "byte_offset", "timestamp_unix", "timestamp_utc", "timestamp_local", "flag_hi", "flag_lo", "category", "alarm_sub_id", "message", "index_flags", "index_ptr", "index_ts_lo", "index_ts_hi")
        Rows = $alarmsRaw
    },
    @{
        Name = "alarms_chronological"
        Headers = @("frame_index", "byte_offset", "timestamp_unix", "timestamp_utc", "timestamp_local", "flag_hi", "flag_lo", "category", "alarm_sub_id", "message", "index_flags", "index_ptr", "index_ts_lo", "index_ts_hi")
        Rows = $alarmsChronological
    },
    @{
        Name = "index_entries"
        Headers = @("frame_index", "flags", "ptr", "ts_lo", "ts_hi", "timestamp_unix", "timestamp_utc", "timestamp_local")
        Rows = $indexRows
    },
    @{
        Name = "category_summary"
        Headers = @("category", "count")
        Rows = $categorySummary
    },
    @{
        Name = "top_messages"
        Headers = @("message", "count")
        Rows = $messageSummary
    },
    @{
        Name = "notes"
        Headers = @("field", "value")
        Rows = $notesRows
    }
)

Write-WorkbookPackage -Path $OutputPath -Sheets $sheets
Write-Output ("Wrote {0}" -f (Resolve-Path $OutputPath).Path)
