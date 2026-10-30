import io
import os
import re
import zipfile
from urllib.parse import unquote

import gdown
import pymupdf
import pytesseract
import requests
import streamlit as st
from markitdown import MarkItDown
from PIL import Image

st.set_page_config(page_title="Smart Document Converter", page_icon="📄", layout="wide")

st.title("📄 Smart Document Converter")
st.write(
    "Convert PDF, Word, PowerPoint, Excel, CSV, HTML, text and other supported "
    "documents into Markdown (.md). Scanned PDFs can be processed with OCR."
)

ALLOWED = {
    "pdf", "docx", "pptx", "xlsx", "xls", "csv", "html", "htm",
    "txt", "json", "xml", "epub", "md"
}

def is_document(name: str) -> bool:
    return name.lower().rsplit(".", 1)[-1] in ALLOWED if "." in name else False

def normal_convert(path: str) -> str:
    return MarkItDown().convert(path).text_content

def ocr_pdf(path: str) -> str:
    document = pymupdf.open(path)
    pages = []
    for page in document:
        pix = page.get_pixmap(dpi=200)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        pages.append(pytesseract.image_to_string(image))
    return "\n\n".join(pages)

def convert_any(path: str):
    if not is_document(path):
        raise ValueError("This file type is not supported.")
    converted_text = normal_convert(path)
    if path.lower().endswith(".pdf") and len(converted_text.strip()) < 50:
        try:
            return ocr_pdf(path), True
        except Exception as exc:
            raise RuntimeError(
                "The PDF appears to need OCR, but OCR could not run. "
                "Please check that Tesseract OCR is installed."
            ) from exc
    return converted_text, False

def markdown_name(path: str) -> str:
    return os.path.splitext(os.path.basename(path))[0] + ".md"

def download_from_drive(link: str, folder: str) -> str:
    match = re.search(
        r"docs\.google\.com/(document|spreadsheets|presentation)/d/([\w-]+)",
        link
    )
    if match:
        kind, file_id = match.groups()
        export_format = {
            "document": "docx",
            "spreadsheets": "xlsx",
            "presentation": "pptx",
        }[kind]
        response = requests.get(
            f"https://docs.google.com/{kind}/d/{file_id}/export?format={export_format}",
            timeout=120,
        )
        if response.status_code != 200 or "text/html" in response.headers.get("Content-Type", ""):
            raise ValueError("Could not access the Google file. Set sharing to 'Anyone with the link'.")
        disposition = response.headers.get("Content-Disposition", "")
        found = (
            re.search(r"filename\*=UTF-8''([^;]+)", disposition)
            or re.search(r'filename="([^"]+)"', disposition)
        )
        filename = unquote(found.group(1)) if found else f"{file_id}.{export_format}"
        destination = os.path.join(folder, os.path.basename(filename))
        with open(destination, "wb") as output:
            output.write(response.content)
        return destination

    downloaded = gdown.download(link, output=folder + "/", fuzzy=True, quiet=True)
    if not downloaded:
        raise ValueError("Could not download the file. Check the link and sharing permissions.")
    return downloaded

def make_zip(file_items):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, content in file_items:
            archive.writestr(filename, content)
    buffer.seek(0)
    return buffer.getvalue()

uploaded_files = st.file_uploader(
    "1. Upload documents from your computer",
    type=sorted(ALLOWED),
    accept_multiple_files=True,
)

st.subheader("2. Or add files using Google Drive links")
drive_links_text = st.text_area(
    "Paste one Google Drive / Google Docs / Sheets / Slides link per line",
    placeholder="https://drive.google.com/file/d/...\nhttps://docs.google.com/document/d/...",
    height=100,
)

st.subheader("3. Or paste notes (optional)")
pasted_text = st.text_area(
    "Paste text you want to convert into a Markdown file",
    placeholder="Paste your notes here...",
    height=120,
)

st.subheader("4. Conversion options")
num_output_files = st.number_input(
    "Number of merged Markdown files",
    min_value=1,
    max_value=20,
    value=2,
    step=1,
    help="The converted documents will be divided as evenly as possible into this many merged files.",
)

if st.button("Convert documents", type="primary", use_container_width=True):
    with st.spinner("Preparing and converting your documents..."):
        import tempfile

        with tempfile.TemporaryDirectory() as temp_folder:
            input_paths = []

            for uploaded in uploaded_files or []:
                safe_name = os.path.basename(uploaded.name)
                if is_document(safe_name):
                    saved_path = os.path.join(temp_folder, safe_name)
                    with open(saved_path, "wb") as output:
                        output.write(uploaded.getbuffer())
                    input_paths.append(saved_path)

            for link in [line.strip() for line in drive_links_text.splitlines() if line.strip()]:
                try:
                    downloaded_path = download_from_drive(link, temp_folder)
                    if is_document(downloaded_path):
                        input_paths.append(downloaded_path)
                    else:
                        st.warning(f"Skipped unsupported file from link: {link}")
                except Exception as exc:
                    st.error(f"Could not download {link}: {exc}")

            if pasted_text.strip():
                pasted_path = os.path.join(temp_folder, "pasted_notes.txt")
                with open(pasted_path, "w", encoding="utf-8") as output:
                    output.write(pasted_text.strip())
                input_paths.append(pasted_path)

            if not input_paths:
                st.warning("Please upload at least one supported document, add a working Drive link, or paste some notes.")
            else:
                results = []
                for path in input_paths:
                    try:
                        converted_text, used_ocr = convert_any(path)
                        output_name = markdown_name(path)
                        results.append((os.path.basename(path), output_name, converted_text, used_ocr))
                    except Exception as exc:
                        st.error(f"Could not convert {os.path.basename(path)}: {exc}")

                if results:
                    st.success(f"Successfully converted {len(results)} file(s).")
                    st.subheader("Converted files")
                    for original_name, output_name, content, used_ocr in results:
                        label = f"{'🔍 OCR' if used_ocr else '✅ Converted'}: {original_name} → {output_name}"
                        with st.expander(label):
                            st.text_area(
                                f"Preview: {output_name}",
                                value=content[:5000],
                                height=180,
                                key=f"preview_{len(results)}_{output_name}",
                            )
                            st.download_button(
                                f"Download {output_name}",
                                data=content.encode("utf-8"),
                                file_name=output_name,
                                mime="text/markdown",
                                key=f"download_{len(results)}_{output_name}",
                            )

                    individual_zip = make_zip(
                        [(output_name, content) for _, output_name, content, _ in results]
                    )
                    st.download_button(
                        "⬇️ Download all individual Markdown files (ZIP)",
                        data=individual_zip,
                        file_name="converted_md_files.zip",
                        mime="application/zip",
                        use_container_width=True,
                    )

                    items = [(original, content) for original, _, content, _ in results]
                    group_count = min(int(num_output_files), len(items))
                    quotient, remainder = divmod(len(items), group_count)
                    groups = []
                    start = 0
                    for index in range(group_count):
                        size = quotient + (1 if index < remainder else 0)
                        groups.append(items[start:start + size])
                        start += size

                    merged_files = []
                    for index, group in enumerate(groups, start=1):
                        body = "\n\n---\n\n".join(
                            f"## Source: {original}\n\n{content}" for original, content in group
                        )
                        merged_files.append((f"merged_{index}_of_{len(groups)}.md", body))

                    merged_zip = make_zip(merged_files)
                    st.download_button(
                        "⬇️ Download merged Markdown files (ZIP)",
                        data=merged_zip,
                        file_name="merged_md_files.zip",
                        mime="application/zip",
                        use_container_width=True,
                    )

st.caption("Tip: For scanned PDFs, OCR works when the Tesseract system package is available.")
