# Manual isolation probe: speech is emitted by PowerShell, never by Chrome.
param([int]$DelaySeconds = 0)
if ($DelaySeconds -gt 0) { Start-Sleep -Seconds $DelaySeconds }
Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
$speaker.SelectVoice('Microsoft Zira Desktop')
for ($index = 0; $index -lt 4; $index++) {
    $speaker.Speak('This speech comes from a different Windows process. Chrome is paused. The translator should remain silent.')
}
