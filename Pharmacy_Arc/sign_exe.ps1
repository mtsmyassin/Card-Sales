# sign_exe.ps1 — Self-Signed Code-Signing for PharmacyDirector.exe
# Run as: powershell -ExecutionPolicy Bypass -File sign_exe.ps1
#
# This creates a self-signed code-signing certificate, exports it to PFX,
# and signs the exe. On the signing machine, "Unknown publisher" is eliminated.
# On OTHER machines, SmartScreen may still warn until a real cert is purchased.

param(
    [string]$ExePath = "dist\PharmacyDirector.exe",
    [string]$PfxPath = "PharmacyDirector.pfx",
    [string]$CertSubject = "CN=Farmacia Carimas, O=Carimas Pharmacy, L=Puerto Rico"
)

$ErrorActionPreference = "Stop"

Write-Host "`n=== PharmacyDirector Code Signing ===" -ForegroundColor Cyan
Write-Host ""

# 1. Check exe exists
if (-not (Test-Path $ExePath)) {
    Write-Host "[ERROR] Executable not found: $ExePath" -ForegroundColor Red
    Write-Host "  Build the exe first with PyInstaller, then run this script."
    exit 1
}

# 2. Check if cert already exists in store
$existingCert = Get-ChildItem Cert:\CurrentUser\My -CodeSigningCert |
    Where-Object { $_.Subject -eq $CertSubject } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1

if ($existingCert -and $existingCert.NotAfter -gt (Get-Date)) {
    Write-Host "[OK] Found existing valid certificate (expires $($existingCert.NotAfter.ToString('yyyy-MM-dd')))" -ForegroundColor Green
    $cert = $existingCert
} else {
    # 3. Generate a new self-signed code-signing certificate (valid 3 years)
    Write-Host "[...] Creating self-signed code-signing certificate..." -ForegroundColor Yellow
    $cert = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject $CertSubject `
        -CertStoreLocation Cert:\CurrentUser\My `
        -NotAfter (Get-Date).AddYears(3) `
        -KeyLength 2048 `
        -HashAlgorithm SHA256

    Write-Host "[OK] Certificate created: $($cert.Thumbprint)" -ForegroundColor Green

    # 4. Trust the cert (add to Trusted Root so local machine recognizes it)
    $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store("Root", "CurrentUser")
    $rootStore.Open("ReadWrite")
    $rootStore.Add($cert)
    $rootStore.Close()
    Write-Host "[OK] Certificate added to Trusted Root CA (CurrentUser)" -ForegroundColor Green
}

# 5. Export to PFX (password-protected)
if (-not (Test-Path $PfxPath)) {
    $pfxPassword = Read-Host -Prompt "Enter a password for the PFX export" -AsSecureString
    Export-PfxCertificate -Cert $cert -FilePath $PfxPath -Password $pfxPassword | Out-Null
    Write-Host "[OK] Certificate exported to $PfxPath" -ForegroundColor Green
} else {
    Write-Host "[OK] PFX already exists: $PfxPath (skipping export)" -ForegroundColor Green
}

# 6. Sign the executable
Write-Host "`n[...] Signing $ExePath ..." -ForegroundColor Yellow
$sigResult = Set-AuthenticodeSignature `
    -FilePath $ExePath `
    -Certificate $cert `
    -TimestampServer "http://timestamp.digicert.com" `
    -HashAlgorithm SHA256

if ($sigResult.Status -eq "Valid") {
    Write-Host "[OK] Signature applied successfully!" -ForegroundColor Green
} else {
    Write-Host "[WARN] Signature status: $($sigResult.Status)" -ForegroundColor Yellow
    Write-Host "  Message: $($sigResult.StatusMessage)"
}

# 7. Verify
Write-Host "`n--- Verification ---" -ForegroundColor Cyan
$sig = Get-AuthenticodeSignature $ExePath
Write-Host "  Status:       $($sig.Status)"
Write-Host "  Signer:       $($sig.SignerCertificate.Subject)"
Write-Host "  Thumbprint:   $($sig.SignerCertificate.Thumbprint)"
Write-Host "  Valid Until:  $($sig.SignerCertificate.NotAfter.ToString('yyyy-MM-dd'))"

# 8. Regenerate SHA256
$hash = (Get-FileHash $ExePath -Algorithm SHA256).Hash
$hash | Out-File -FilePath "$ExePath.sha256" -Encoding ascii -NoNewline
Write-Host "`n  SHA256: $hash"
Write-Host "  Written to $ExePath.sha256"

Write-Host "`n=== Done ===" -ForegroundColor Cyan
Write-Host ""
