import os
import glob
from pyhanko.sign import signers, fields
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.pdf_utils import generic
from pyhanko.pdf_utils.layout import BoxConstraints

from config import CERTIFICATE_FOLDER, FORM16_SIGNED_FOLDER

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
        signer = signers.SimpleSigner.load_pkcs12(cert_path, cert_password.encode('utf-8'))
    except Exception as e:
        raise ValueError(f"Invalid certificate or password: {e}")

    try:
        with open(input_pdf_path, 'rb') as doc_in:
            w = IncrementalPdfFileWriter(doc_in)
            
            # Check if signature field exists, create if not
            field_name = 'Signature1'
            acro_form = w.root.get('/AcroForm')
            fields_dict = acro_form.get('/Fields') if acro_form else None
            
            field_exists = False
            if fields_dict:
                for field_ref in fields_dict:
                    field = field_ref.get_object()
                    if field.get('/T') == field_name:
                        field_exists = True
                        break
            
            if not field_exists:
                # Create signature field automatically
                sig_field_spec = fields.SigFieldSpec(
                    field_name=field_name,
                    box=BoxConstraints(width=200, height=50)
                )
                sig_field_spec.embed(
                    w, 
                    page=0,  # Add to first page
                    x=400, y=50  # Position on page (adjust as needed)
                )
            
            with open(output_pdf_path, 'wb') as doc_out:
                meta = signers.PdfSignatureMetadata(field_name=field_name)
                signers.sign_pdf(w, meta, signer=signer, out_file=doc_out)
        return True
    except Exception as e:
        raise RuntimeError(f"Error signing PDF: {e}")
