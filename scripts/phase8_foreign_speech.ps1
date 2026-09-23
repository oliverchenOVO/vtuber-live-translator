# Authored, synthetic speech from a non-Chrome process. No audio file is created.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$speakerProbe = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $speakerProbe.SetOutputToDefaultAudioDevice()
    $speakerProbe.Rate = 0
    for ($iteration = 0; $iteration -lt 6; $iteration++) {
        $speakerProbe.Speak('Purple kangaroos count three hundred seventy one. This is the separate application isolation test.')
    }
} finally {
    $speakerProbe.Dispose()
}
