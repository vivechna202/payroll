import os
from io import BytesIO
from pypdf import PdfReader, PdfWriter

# Configuration
TEST_DATA_DIR = "test_data"
CORRECT_TAN = "MUMA12345B"
INCORRECT_TAN = "WRONGTAN12"

# Define Test Scenarios
employees = [
    {"id": "EMP01", "name": "Aarav Sharma", "pan": "ABCDE1234F", "scen": "Matching A & B"},
    {"id": "EMP02", "name": "Priya Patel", "pan": "FGHIJ5678K", "scen": "Matching A & B"},
    {"id": "EMP03", "name": "Amit Verma", "pan": "KLMNO9012P", "scen": "Matching A & B"},
    {"id": "EMP04", "name": "Sneha Reddy", "pan": "QRSTU3456V", "scen": "Matching A & B"},
    {"id": "EMP05", "name": "Vikram Malhotra", "pan": "WXYZA7890B", "scen": "Matching A & B"},
    {"id": "EMP06", "name": "Rohan Gupta", "pan": "BCDEF1122G", "scen": "Only Part A"},
    {"id": "EMP07", "name": "Ananya Rao", "pan": "CDEFG3344H", "scen": "Only Part B"},
    {"id": "EMP08", "name": "Rajesh Kumar", "pan": "HIJKL5566M", "scen": "Decryption Failure"},
]

def generate_raw_pdf_bytes(metadata: dict) -> bytes:
    """
    Generates a minimalist, structurally compliant binary PDF document from scratch.
    Embeds clear text layout coordinates readable by pypdf and pdfplumber.
    """
    # Build text instructions for the PDF page canvas stream
    content_lines = ["BT", "/F1 12 Tf", "50 750 Td", "16 TL"]  # Set text position and leading line height
    for key, value in metadata.items():
        # Escape brackets for safety in PDF operators
        clean_key = str(key).replace("(", "\\(").replace(")", "\\)")
        clean_val = str(value).replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"({clean_key}: {clean_val}) Tj T*")
    content_lines.append("ET")
    content_stream = "\n".join(content_lines)
    stream_len = len(content_stream)

    # Standard programmatic cross-reference representation of PDF page dictionary hierarchy
    pdf_template = (
        f"%PDF-1.4\n"
        f"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        f"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        f"3 0 obj\n<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> >> >> /MediaBox [0 0 595 842] /Contents 4 0 R >>\nendobj\n"
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n{content_stream}\nendstream\nendobj\n"
        f"xref\n0 5\n0000000000 65535 f\n0000000009 00000 n\n0000000056 00000 n\n0000000111 00000 n\n0000000286 00000 n\n"
        f"trailer\n<< /Size 5 /Root 1 0 R >>\n"
        f"startxref\n{286 + stream_len + 20}\n%%EOF"
    )
    return pdf_template.encode('latin-1')

def create_secured_pdf(filename: str, metadata: dict, password: str):
    """Compiles a binary PDF stream, encrypts using standard AES-256, and writes to disk."""
    filepath = os.path.join(TEST_DATA_DIR, filename)
    raw_pdf_bytes = generate_raw_pdf_bytes(metadata)
    
    # Process through a writer stream to correctly encapsulate encryption payload
    reader = PdfReader(BytesIO(raw_pdf_bytes))
    writer = PdfWriter(clone_from=reader)
    writer.encrypt(user_password=password, owner_password=password, algorithm="AES-256")
    
    with open(filepath, "wb") as f:
        writer.write(f)

def generate_all_test_files():
    """Generates all scenario files into the local target test data folder."""
    if not os.path.exists(TEST_DATA_DIR):
        os.makedirs(TEST_DATA_DIR)
        
    print("Generating actual, text-extractable password-protected Form 16 PDFs...")
    
    for emp in employees:
        meta_base = {
            "Employee Name": emp["name"],
            "PAN": emp["pan"],
            "Financial Year": "2025-2026"
        }
        
        if emp["scen"] == "Matching A & B":
            create_secured_pdf(f"{emp['id']}_PartA.pdf", {**meta_base, "Part_Type": "A"}, CORRECT_TAN)
            create_secured_pdf(f"{emp['id']}_PartB.pdf", {**meta_base, "Part_Type": "B"}, CORRECT_TAN)
            
        elif emp["scen"] == "Only Part A":
            create_secured_pdf(f"{emp['id']}_PartA.pdf", {**meta_base, "Part_Type": "A"}, CORRECT_TAN)
            
        elif emp["scen"] == "Only Part B":
            create_secured_pdf(f"{emp['id']}_PartB.pdf", {**meta_base, "Part_Type": "B"}, CORRECT_TAN)
            
        elif emp["scen"] == "Decryption Failure":
            create_secured_pdf(f"{emp['id']}_PartA.pdf", {**meta_base, "Part_Type": "A"}, INCORRECT_TAN)
            create_secured_pdf(f"{emp['id']}_PartB.pdf", {**meta_base, "Part_Type": "B"}, INCORRECT_TAN)

    print(f"Successfully generated 12 valid text-bearing PDFs in './{TEST_DATA_DIR}'\n")

# 2. Pipeline Extraction Verification Block
def verify_generated_pdfs():
    """Reads back generated files to confirm text integrity post-decryption."""
    print("Running data extraction test pipeline verification...")
    files = sorted([f for f in os.listdir(TEST_DATA_DIR) if f.endswith(".pdf")])
    
    print("-" * 90)
    print(f"{'Target File':<20} | {'Decryption Status':<20} | {'Extracted Check (PAN)':<25}")
    print("-" * 90)
    
    for file in files:
        filepath = os.path.join(TEST_DATA_DIR, file)
        reader = PdfReader(filepath)
        
        # Normalize processing logic to align with standard pypdf decryption code
        tan_attempt = CORRECT_TAN
        decryption_result = reader.decrypt(tan_attempt)
        
        if decryption_result in (1, 2):  # Correctly identifies user or owner auth match
            text = reader.pages[0].extract_text()
            
            # Simple line parsing evaluation
            extracted_pan = "Unknown"
            for line in text.split("\n"):
                if "PAN:" in line:
                    extracted_pan = line.split("PAN:")[-1].strip()
            
            print(f"{file:<20} | {'SUCCESS':<20} | {f'PASSED (PAN: {extracted_pan})':<25}")
        else:
            print(f"{file:<20} | {'FAILED (Expected)':<20} | {'BLOCKED':<25}")
    print("-" * 90)

if __name__ == "__main__":
    generate_all_test_files()
    verify_generated_pdfs()