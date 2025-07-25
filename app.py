import os
import streamlit as st
from dotenv import load_dotenv
import time
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from openai import AzureOpenAI
from analyze_invoice import analyze_invoice_from_pdf, analyze_invoice_any
import base64
# ------------------
# ENV + CLIENTS
# ------------------
load_dotenv()
API_ENDPOINT = os.getenv("AZURE_OPENAI_ENDPOINT")
API_KEY = os.getenv("AZURE_OPENAI_API_KEY")
DOC_ENDPOINT = os.getenv("AZURE_DOC_ENDPOINT")
DOC_KEY = os.getenv("AZURE_DOC_KEY")
CHAT_MODEL = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-35-turbo")

openai_client = AzureOpenAI(
    azure_endpoint=API_ENDPOINT,
    api_key=API_KEY,
    api_version="2024-02-01"
)

doc_client = DocumentIntelligenceClient(DOC_ENDPOINT, AzureKeyCredential(DOC_KEY))



# ------------------
# HELPERS
# ------------------

def image_to_base64(img_bytes):
    return base64.b64encode(img_bytes).decode("utf-8")

def ask_llm(user_messages):
    base_context = [
        {
            "role": "system",
            "content": "You are a helpful assistant that can see all provided invoice images and answer questions based on them and the extracted text."
        }
    ]

    if "invoice_data" in st.session_state:
        invoice_text, _, images = st.session_state.invoice_data

        user_content = [{"type": "text", "text": invoice_text}]
        for img_bytes in images:
            img_b64 = image_to_base64(img_bytes)
            user_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
            })

        base_context.append({"role": "user", "content": user_content})

    all_messages = base_context + user_messages

    

    print("\n[DEBUG] Sending messages to GPT:")
    for i, m in enumerate(all_messages):
        print(f"  {i}. {m['role'].upper()}: {m.get('content')}")
    print("[DEBUG] ---- End of messages ----\n")

    # Stream
    # ... build all_messages ...
    response_stream = openai_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=all_messages,
        stream=True
    )

    full_text = ""
    # Instead of st.empty(), use a container inside the assistant message bubble
    container = st.empty()

    for event in response_stream:
        if not event.choices or not event.choices[0].delta:
            continue

        token = getattr(event.choices[0].delta, "content", "")
        if token:
            full_text += token
            container.markdown(full_text)
            time.sleep(0.02)  # typing feel (adjust speed here)

    return full_text




def init_chat_if_needed(invoice_text: str):
    """Initialize multi-turn chat state once per uploaded invoice."""
    if "messages" not in st.session_state:
        st.session_state.messages = [
            {
                "role": "system",
                "content": "You are a helpful assistant answering questions strictly based on the provided invoice data."
            },
            {
                "role": "user",
                "content": invoice_text
            }
        ]


# ------------------
# UI
# ------------------
st.set_page_config(page_title="Invoice Chat", page_icon="🧾")
st.title("📄 Chat with Invoice (Azure Document Intelligence + OpenAI)")

col1, col2 = st.columns(2)
with col1:
    reset_chat_clicked = st.button("🔄 Reset chat", use_container_width=True)
with col2:
    clear_invoice_clicked = st.button("🗑️ Clear invoice", type="secondary", use_container_width=True)

if reset_chat_clicked and "invoice_data" in st.session_state:
    invoice_text, _, _ = st.session_state.invoice_data
    st.session_state.messages = []
    init_chat_if_needed(invoice_text)

if clear_invoice_clicked:
    for k in ("invoice_data", "messages", "uploaded_name"):
        if k in st.session_state:
            del st.session_state[k]
    st.rerun()

uploaded = st.file_uploader(
    "Upload an invoice (PDF/image)",
    type=["pdf", "png", "jpg", "jpeg"]
)

if uploaded:
    # Re-process if it’s a new file (by name) or we don't have cached data
    if (
        "invoice_data" not in st.session_state
        or st.session_state.get("uploaded_name") != uploaded.name
    ):
        raw = uploaded.read()
        st.info("Extracting invoice via Azure Document Intelligence…")
        # invoice_text, fields, images = analyze_invoice_from_pdf(raw)
        # invoice_text, fields, images = analyze_invoice_file(raw, uploaded.name)
        invoice_text, fields, images = analyze_invoice_any(raw, filename=uploaded.name, mime=uploaded.type)


        if fields is None:
            st.error("Could not extract invoice fields.")
            st.stop()
        st.success("Invoice data extracted!")
        st.session_state.invoice_data = (invoice_text, fields, images)
        st.session_state.uploaded_name = uploaded.name
        st.session_state.messages = []
        init_chat_if_needed(invoice_text)
    else:
        invoice_text, fields, images = st.session_state.invoice_data
        init_chat_if_needed(invoice_text)

    # ------------------
    # Show extracted info + invoice text side by side
    # ------------------
    left, right = st.columns(2)
    with left:
        st.subheader("📋 Parsed Fields")
        st.json(fields)
    with right:
        st.subheader("🧾 Invoice Text")
        st.code(invoice_text)

    # ------------------
    # Multi-turn chat UI
    # ------------------
    st.write("### 💬 Chat")
    for m in st.session_state.messages:
        if m["role"] == "system":
            continue
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    prompt = st.chat_input("Ask something about this invoice…")
    if prompt:
        # Display the user's message bubble
        with st.chat_message("user"):
            st.markdown(prompt)

        # Add to message history
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Display assistant's bubble and stream reply
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                reply = ask_llm(st.session_state.messages)

        st.session_state.messages.append({"role": "assistant", "content": reply})
    else:
        st.info("You may begin the conversation now")
        
