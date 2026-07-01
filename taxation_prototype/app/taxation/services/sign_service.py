import os
import glob
from pyhanko.sign import signers, fields
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils.layout import BoxConstraints

from app.base.utils.config import CERTIFICATE_FOLDER, FORM16_SIGNED_FOLDER

os.makedirs(CERTIFICATE_FOLDER, exist_ok=True)
os.makedirs(FORM16_SIGNED_FOLDER, exist_ok=True)

def has_certificate():
    """Check if any .pfx or .p12 certificate is uploaded."""
    certs = glob.glob(os.path.join(CERTIFICATE_FOLDER, "*.pfx")) + glob.glob(os.path.join(CERTIFICATE_FOLDER, "*.p12"))
    return len(certs) > 0

def get_certificate_path():
    """Return the path to the first configured certificate."""
    certs = glob.glob(os.path.join(CERTIFICATE_FOLDER, "*.pfx")) + glob.glob(os.path.join(CERTIFICATE_FOLDER, "*.p12"))
    if certs:
        return certs[0]
    return None

def save_certificate(file_obj):
    """Save an uploaded certificate to the certificates folder."""
    filename = file_obj.filename
    if not (filename.endswith(".pfx") or filename.endswith(".p12")):
        raise ValueError("Only .pfx or .p12 files are allowed")
    
    # Clear existing certs first to ensure only one is active
    for cert in glob.glob(os.path.join(CERTIFICATE_FOLDER, "*.pfx")) + glob.glob(os.path.join(CERTIFICATE_FOLDER, "*.p12")):
        os.remove(cert)
        
    path = os.path.join(CERTIFICATE_FOLDER, filename)
    file_obj.save(path)
    return True

def sign_pdf(input_pdf_path, output_pdf_path, cert_password):
    """
    Sign the input PDF using the configured certificate and pyHanko.
    
    SIGNING-ONLY IMPLEMENTATION:
    - Uses ONLY signers.SimpleSigner.load_pkcs12() for certificate loading
    - NO CA chain loading or trust validation
    - NO verification logic (verification should be handled separately)
    - Works with self-signed certificates for testing
    - Automatically creates signature field if it doesn't exist
    
    Args:
        input_pdf_path: Path to input PDF file
        output_pdf_path: Path for signed PDF output
        cert_password: Password for .p12/.pfx certificate
    
    Returns:
        True if signing successful
    
    Raises:
        FileNotFoundError: If no certificate configured
        ValueError: If certificate or password invalid
        RuntimeError: If PDF signing fails
    """
    cert_path = get_certificate_path()
    if not cert_path:
        raise FileNotFoundError("No certificate configured.")
        
    # Load certificate using ONLY SimpleSigner.load_pkcs12 (no CA chain, no trust validation)
    try:
        print(f"[DEBUG] Loading certificate from: {cert_path}")
        print(f"[DEBUG] Certificate file exists: {os.path.exists(cert_path)}")
        
        # Explicitly pass None for ca_chain to prevent CA chain loading
        signer = signers.SimpleSigner.load_pkcs12(
            cert_path, 
             passphrase=cert_password.encode("utf-8") #Explicitly disable CA chain loading
        )
        print("Signer:", signer)
        print(f"[DEBUG] Certificate loaded successfully from: {cert_path}")
        print(f"[DEBUG] Signer type: {type(signer)}")
    except Exception as e:
        print(f"[ERROR] Failed to load certificate: {e}")
        import traceback
        traceback.print_exc()
        raise ValueError(f"Invalid certificate or password: {e}")
    
    # Explicit validation: ensure signer is not None
    if signer is None:
        print(f"[ERROR] Signer is None after certificate loading")
        raise ValueError("Certificate not loaded or invalid")
    
    print(f"[DEBUG] Signer object initialized successfully")

    try:
        print(f"[DEBUG] Starting PDF signing process")
        print(f"[DEBUG] Input PDF: {input_pdf_path}")
        print(f"[DEBUG] Output PDF: {output_pdf_path}")
        
        with open(input_pdf_path, 'rb') as doc_in:
            w = IncrementalPdfFileWriter(doc_in)
            print(f"[DEBUG] IncrementalPdfFileWriter initialized")
            
            # Check if signature field exists, create if not
            field_name = 'Signature1'
            acro_form = w.root.get('/AcroForm')
            
            field_exists = False
            if acro_form:
                fields_arr = acro_form.get('/Fields')
                if fields_arr:
                    for field_ref in fields_arr:
                        field = field_ref.get_object() if hasattr(field_ref, 'get_object') else field_ref
                        if isinstance(field, dict):
                            t_val = field.get('/T')
                            if t_val == field_name or t_val == field_name.encode('utf-8'):
                                field_exists = True
                                break
            
            print(f"[DEBUG] Signature field exists: {field_exists}")
            
            if not field_exists:
                # Create signature field automatically
                print(f"[DEBUG] Creating signature field")
                sig_field_spec = fields.SigFieldSpec(
                    field_name,
                    on_page=0,
                    box=(400, 50, 600, 100)
                )
                fields.append_signature_field(
                    w,
                    sig_field_spec
                )
                print(f"[DEBUG] Signature field created successfully")
            
            print(f"[DEBUG] Preparing signature metadata")
            meta = signers.PdfSignatureMetadata(field_name=field_name)
            print(f"[DEBUG] Calling signers.sign_pdf with signer")
            out_stream = signers.sign_pdf(w, signature_meta=meta, signer=signer)
            print(f"[DEBUG] PDF signed successfully, writing to output")
            with open(output_pdf_path, 'wb') as doc_out:
                doc_out.write(out_stream.read())
        print(f"[DEBUG] PDF signing completed successfully")
        return True
    except Exception as e:
        print(f"[ERROR] Error during PDF signing: {e}")
        import traceback
        traceback.print_exc()
        raise RuntimeError(f"Error signing PDF: {e}")
