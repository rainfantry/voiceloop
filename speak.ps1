param([string]$text, [int]$rate = 2)
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = $rate
$synth.Speak($text)
$synth.Dispose()
