# Finds or creates the DEVELOPMENT code-signing certificate and prints its thumbprint.
#
# It is self-signed and lives only in your Windows certificate store (CurrentUser\My); it is never
# exported or committed. Windows (and SmartScreen) do not trust it, so it only proves that the
# signing step works. The production OV/EV certificate replaces it later (docs/runbooks/local-dev.md).
param([string]$Subject = "CN=Hirevion Dev Code Signing (not trusted)")

$ErrorActionPreference = "Stop"
$cert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
  Where-Object { $_.Subject -eq $Subject -and $_.NotAfter -gt (Get-Date).AddDays(7) } |
  Sort-Object NotAfter -Descending |
  Select-Object -First 1
if (-not $cert) {
  $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject $Subject `
    -KeyAlgorithm RSA -KeyLength 3072 -HashAlgorithm SHA256 `
    -CertStoreLocation Cert:\CurrentUser\My -NotAfter (Get-Date).AddYears(1)
}
Write-Output $cert.Thumbprint
