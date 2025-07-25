import os
import fitz  # PyMuPDF
from dotenv import load_dotenv
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
import json
import streamlit as st




load_dotenv()

def analyze_invoice_image(image_bytes: bytes):
    # Initialize the Document Intelligence client
    endpoint = os.getenv("AZURE_DOC_ENDPOINT")
    key = os.getenv("AZURE_DOC_KEY")
    client = DocumentIntelligenceClient(endpoint, AzureKeyCredential(key))

    poller = client.begin_analyze_document(
        model_id="prebuilt-invoice",
        body=image_bytes
    )
    return poller.result()

# def pdf_to_images(pdf_path: str):
#     doc = fitz.open(pdf_path)
#     for page_num in range(len(doc)):
#         page = doc[page_num]
#         pix = page.get_pixmap(dpi=300)  # Render at 300 DPI for good OCR quality
#         yield pix.tobytes("png")  # Yield each page as PNG bytes

def pdf_bytes_to_images(pdf_bytes: bytes):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")  # Open PDF directly from memory
    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(dpi=300)
        yield pix.tobytes("png")




def get_table_dict(result):
    tables = result.get("tables", [])
    print("number of tables",len(tables))
    if len(tables) != 0:
        table_dict = {}
        table_count = 0
        for i in tables:
            table_count+=1
            cells = i.get("cells", [])
            print("number of cells in table", table_count, len(cells))
            if len(cells) != 0:
                header_present = False
                map_header = {}
                for j in cells:
                    header = j.get("kind", "")
                    if header == "columnHeader":
                        header_present = True
                        map_header[j.get("columnIndex","abc")] = j.get("content", "") 
                    else:
                        header_present = False
                        break
                print("map_header", map_header)
                row_list = []
                row_dict = {}
                row_element = []
                if not map_header:
                    # make key value
                    last_row_index = 0
                    for j in cells:
                        row_index = j.get("rowIndex", 0)
                        if row_index == last_row_index:
                            row_element.append(j.get("content", ""))
                            row_dict[row_index] = row_element
                        else:
                            row_list.append(row_dict)
                            row_dict = {}
                            row_element = []
                            row_element.append(j.get("content", ""))
                            row_dict[row_index] = row_element
                        last_row_index = row_index
                    
                    table_dict[table_count] = row_list
                    

                            

                else:
                    print("map header not empty")
                    d_list = []
                    dict_row = {}
                    for j in cells:
                        print("j", j)
                        if j.get("kind", "") == "columnHeader":
                            last_row_index = j.get("rowIndex", 0)
                            continue
                        column_index = j.get("columnIndex", "abc")
                        row_index = j.get("rowIndex", 0)

                        column_element = j.get("content", "")
                        if column_element == "":
                            continue
                        if row_index == last_row_index:
                            dict_row[map_header[column_index]] = j.get("content", "")
                        else:
                            d_list.append(dict_row)
                            dict_row = {}
                            dict_row[map_header[column_index]] = j.get("content", "")
                        
                        last_row_index = row_index

                        if column_index in map_header:
                            j["header"] = map_header[column_index]
                        else:
                            j["header"] = ""
                    table_dict[table_count] = d_list
        return table_dict
                    
def process_tables_to_string(table_dict):
    def is_digit_key(k):
        return isinstance(k, int) or (isinstance(k, str) and k.isdigit())

    def looks_like_no_header_row(row: dict) -> bool:
        """Row like {"0": [...], "1": [...]} => treat as no-header row."""
        if not isinstance(row, dict) or not row:
            return False
        # Check *all* keys are digit-like and *all* values are lists/tuples
        return all(is_digit_key(k) for k in row.keys()) and \
               all(isinstance(v, (list, tuple)) for v in row.values())

    def is_no_header_table(rows):
        """A table is 'no-header' if every non-empty row looks like a no-header row."""
        for r in rows:
            if not r:  # skip empty dicts
                continue
            if not looks_like_no_header_row(r):
                return False
        return True

    def key_sorter(k):
        """Sort numeric keys numerically, others lexicographically."""
        kstr = str(k)
        return (0, int(kstr)) if kstr.isdigit() else (1, kstr)

    def format_no_header_table(table_id, rows):
        lines = [f"Table {table_id} (no headers or we couldn't detect headers):"]
        for i, row in enumerate(rows):
            if not isinstance(row, dict) or not row:
                continue
            parts = []
            for k in sorted(row.keys(), key=key_sorter):
                v = row[k]
                if isinstance(v, (list, tuple)):
                    parts.append(" | ".join(map(str, v)))
                else:
                    parts.append(str(v))
            if parts:
                lines.append(f"  - Row {i}: " + " || ".join(parts))
        return "\n".join(lines)

    result_lines = []

    for tid, content in table_dict.items():
        rows = content if isinstance(content, list) else ([content] if isinstance(content, dict) else [])
        if is_no_header_table(rows):
            result_lines.append(format_no_header_table(tid, rows))
        else:
            # Treat as header table → dump as JSON
            result_lines.append(f"Table {tid} (headers):\n{json.dumps(rows, ensure_ascii=False, indent=2)}")

    return "\n\n".join(result_lines)

def analyze_invoice_from_pdf(bytes_data: bytes):
    output_strs = ""
    td = {}
    images = []
    for i, img_bytes in enumerate(pdf_bytes_to_images(bytes_data), start=1):
        print(f"\n--- Analyzing page {i} ---")
        st.write(f"--- Analyzing page {i} ---")
        images.append(img_bytes)
        result = analyze_invoice_image(img_bytes)
        result_json = result.as_dict()
        print(result_json)
        table_dict = get_table_dict(result_json)
        if not isinstance(table_dict, dict) or not table_dict:
            print("table_dict is either not a dict or is empty")
            table_dict={}
        else:
            print("table_dict is a non-empty dict")
        td = {**td, **table_dict}
        output_str = process_tables_to_string(table_dict)
        output_strs += f"\n\n--- Page {i} ---\n{output_str}"
    
    return output_strs,td,images
