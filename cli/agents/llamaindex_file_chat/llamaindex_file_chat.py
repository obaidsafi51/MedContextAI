import asyncio
import os
import tempfile
from typing import Annotated, Optional, Dict, Any
from dotenv import load_dotenv
from genai_session.session import GenAISession
from genai_session.utils.context import GenAIContext

# LlamaIndex imports
from llama_index.core import VectorStoreIndex, Document, Settings
from llama_index.core.workflow import (
    Context,
    Event,
    StartEvent,
    StopEvent,
    Workflow,
    step,
)
from llama_index.llms.openai import OpenAI
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.memory import ChatMemoryBuffer

# LlamaParse for document parsing
try:
    from llama_parse import LlamaParse
except ImportError:
    LlamaParse = None
    logger.warning("LlamaParse not available. Install with: pip install llama-parse")

import logging


# Load environment variables from .env file
load_dotenv()

# Load environment variables from .env file
load_dotenv()
OPENAI_API_KEY="Pate your OpenAI API key here"
OPENAI_MODEL="gpt-4o-mini"
OPENAI_TEMPERATURE=0.6
OPENAI_EMBEDDING_MODEL="text-embedding-3-small"
AGENT_JWT = "Pate your JWT token here" # noqa: E501
session = GenAISession(jwt_token=AGENT_JWT)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configure LlamaIndex settings
Settings.llm = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    temperature=float(os.getenv("OPENAI_TEMPERATURE", "0.1"))
)
Settings.embed_model = OpenAIEmbedding(
    api_key=os.getenv("OPENAI_API_KEY"),
    model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
)
Settings.node_parser = SentenceSplitter(chunk_size=1024, chunk_overlap=20)

# Global storage for conversation contexts
conversation_contexts: Dict[str, Any] = {}

class WorkflowInput(Event):
    """Input event for the workflow"""
    message: str
    session_id: str
    file_content: Optional[bytes] = None
    file_name: Optional[str] = None

class ParseEvent(Event):
    """Event for document parsing"""
    file_content: bytes
    file_name: str
    session_id: str
    original_message: str

class ChatEvent(Event):
    """Event for chat processing"""
    message: str
    session_id: str
    has_context: bool = False

class ParseAndChatWorkflow(Workflow):
    """LlamaIndex Workflow for parsing files and chatting"""
    
    def __init__(self, timeout: int = 60, verbose: bool = False):
        super().__init__(timeout=timeout, verbose=verbose)
    
    @step
    async def start_workflow(self, ctx: Context, ev: StartEvent) -> ParseEvent | ChatEvent:
        """Entry point for the workflow - handles StartEvent"""
        # Extract the input from the StartEvent
        workflow_input: WorkflowInput = ev.get("input")
        
        # Check if there's a file to parse
        if workflow_input.file_content and workflow_input.file_name:
            logger.info(f"Starting workflow with file parsing: {workflow_input.file_name}")
            return ParseEvent(
                file_content=workflow_input.file_content,
                file_name=workflow_input.file_name,
                session_id=workflow_input.session_id,
                original_message=workflow_input.message
            )
        else:
            logger.info(f"Starting workflow with chat only for session: {workflow_input.session_id}")
            return ChatEvent(
                message=workflow_input.message,
                session_id=workflow_input.session_id
            )
    
    @step
    async def parse_document(self, ctx: Context, ev: ParseEvent) -> ChatEvent:
        """Parse uploaded document and create index using LlamaParse"""
        try:
            logger.info(f"Parsing document: {ev.file_name} for session: {ev.session_id}")
            
            # Get the file extension from the original filename
            file_extension = ""
            if '.' in ev.file_name:
                file_extension = os.path.splitext(ev.file_name)[1].lower()
            
            # Create temporary file with correct extension
            temp_file_suffix = f"_{ev.file_name}" if file_extension else f"_{ev.file_name}.pdf"
            
            with tempfile.NamedTemporaryFile(delete=False, suffix=temp_file_suffix) as temp_file:
                temp_file.write(ev.file_content)
                temp_file_path = temp_file.name
            
            try:
                # Check if LlamaParse is available and configured
                llama_cloud_api_key = os.getenv("LLAMA_CLOUD_API_KEY")
                if not llama_cloud_api_key or not LlamaParse:
                    logger.warning("LlamaParse not configured, falling back to simple text extraction")
                    # Fallback to simple text extraction
                    try:
                        with open(temp_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                            content = f.read()
                    except Exception:
                        with open(temp_file_path, 'rb') as f:
                            content = f.read().decode('utf-8', errors='ignore')
                else:
                    # Use LlamaParse for document parsing
                    logger.info(f"Using LlamaParse to parse: {ev.file_name} (extension: {file_extension})")
                    
                    parser = LlamaParse(
                        api_key=llama_cloud_api_key,
                        result_type="markdown",  # Use markdown for better structure
                        verbose=True
                    )
                    
                    try:
                        # Parse the document
                        documents = await parser.aload_data(temp_file_path)
                        
                        if documents:
                            # Combine all document content
                            content = "\n\n".join([doc.text for doc in documents])
                            logger.info(f"LlamaParse successfully parsed {ev.file_name}, extracted {len(content)} characters")
                        else:
                            logger.warning(f"LlamaParse returned no content for {ev.file_name}")
                            content = ""
                    except Exception as parse_error:
                        logger.error(f"LlamaParse failed for {ev.file_name}: {str(parse_error)}")
                        # Fallback to simple text extraction
                        logger.info("Falling back to simple text extraction")
                        try:
                            with open(temp_file_path, 'r', encoding='utf-8', errors='ignore') as f:
                                content = f.read()
                        except Exception:
                            with open(temp_file_path, 'rb') as f:
                                content = f.read().decode('utf-8', errors='ignore')
                
                if not content.strip():
                    logger.warning(f"No readable content extracted from file: {ev.file_name}")
                    return ChatEvent(
                        message=f"I wasn't able to extract readable content from '{ev.file_name}'. This might be due to the file format, file being empty, or parsing issues. The file appears to be {file_extension or 'unknown type'}. Please try uploading a different file or ensure it contains readable text.",
                        session_id=ev.session_id,
                        has_context=False
                    )
                
                # Create document from parsed content
                document = Document(
                    text=content,
                    metadata={
                        "file_name": ev.file_name,
                        "file_extension": file_extension,
                        "source": "llama_parse" if llama_cloud_api_key and LlamaParse else "fallback",
                        "content_length": len(content)
                    }
                )
                
                logger.info(f"Creating vector index for document: {ev.file_name}")
                
                # Create vector index
                index = VectorStoreIndex.from_documents([document])
                
                # Store in conversation context
                conversation_contexts[ev.session_id] = {
                    "index": index,
                    "file_name": ev.file_name,
                    "chat_memory": ChatMemoryBuffer.from_defaults(token_limit=3000),
                    "document_content_preview": content[:200] + "..." if len(content) > 200 else content,
                    "content_length": len(content),
                    "file_extension": file_extension,
                    "parsed_with": "llama_parse" if llama_cloud_api_key and LlamaParse else "fallback"
                }
                
                logger.info(f"Document parsed successfully: {ev.file_name}, stored in session: {ev.session_id}")
                logger.info(f"Context stored for session {ev.session_id}: {list(conversation_contexts.keys())}")
                
                # If there was an original message, process it; otherwise, just return confirmation
                if ev.original_message and ev.original_message.strip():
                    message_to_process = ev.original_message
                else:
                    parse_method = "LlamaParse" if llama_cloud_api_key and LlamaParse else "text extraction"
                    message_to_process = f"I've successfully parsed your file '{ev.file_name}' ({file_extension or 'unknown type'}) using {parse_method}. The document contains {len(content)} characters of content. You can now ask me questions about its content."
                
                return ChatEvent(
                    message=message_to_process,
                    session_id=ev.session_id,
                    has_context=True
                )
            
            finally:
                # Clean up temporary file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    
        except Exception as e:
            logger.error(f"Error parsing document: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return ChatEvent(
                message=f"Sorry, I encountered an error while parsing your file '{ev.file_name}': {str(e)}. Please try uploading a different file.",
                session_id=ev.session_id,
                has_context=False
            )
    
    @step
    async def chat_with_context(self, ctx: Context, ev: ChatEvent) -> StopEvent:
        """Handle chat with document context"""
        try:
            logger.info(f"Processing chat for session: {ev.session_id}")
            logger.info(f"Available sessions in context: {list(conversation_contexts.keys())}")
            
            session_context = conversation_contexts.get(ev.session_id)
            
            if session_context and "index" in session_context:
                logger.info(f"Found document context for session {ev.session_id}: {session_context['file_name']}")
                
                # Create chat engine with context
                chat_engine = session_context["index"].as_chat_engine(
                    chat_mode="context",
                    memory=session_context["chat_memory"],
                    system_prompt=(
                        "You are an AI assistant that helps users understand and analyze documents. "
                        "Use the document content to provide accurate and helpful responses. "
                        "If the question cannot be answered from the document, say so clearly. "
                        "Always cite specific parts of the document when possible."
                    )
                )
                
                # Get response from chat engine
                logger.info(f"Querying chat engine with: {ev.message}")
                response = await chat_engine.achat(ev.message)
                
                # Extract citations if available
                citations = []
                if hasattr(response, 'source_nodes') and response.source_nodes:
                    for node in response.source_nodes:
                        if hasattr(node, 'metadata') and 'file_name' in node.metadata:
                            citations.append({
                                "file_name": node.metadata['file_name'],
                                "content_snippet": node.text[:200] + "..." if len(node.text) > 200 else node.text
                            })
                
                result = {
                    "response": str(response.response),
                    "has_context": True,
                    "file_name": session_context.get("file_name"),
                    "citations": citations
                }
                
                logger.info(f"Generated response with {len(citations)} citations")
                
            else:
                logger.warning(f"No document context found for session {ev.session_id}")
                # No document context available
                result = {
                    "response": "I don't have any document context. Please upload a file first so I can answer questions about it.",
                    "has_context": False,
                    "citations": []
                }
            
            return StopEvent(result=result)
            
        except Exception as e:
            logger.error(f"Error in chat processing: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return StopEvent(result={
                "response": f"Sorry, I encountered an error while processing your question: {str(e)}",
                "has_context": False,
                "citations": []
            })

# Initialize workflow
workflow = ParseAndChatWorkflow(timeout=120, verbose=True)

@session.bind(
    name="llamaindex_file_chat",
    description="A conversational EASAgent that parses medical files and generates structured summaries with PDF using LlamaIndex and OpenAI"
)
async def llamaindex_file_chat(
    agent_context: GenAIContext,
    message: Annotated[str, "User message or summary instruction."],
    file_id: Annotated[Optional[str], "Optional file ID to parse"] = None
):
    try:
        session_id = agent_context.session_id
        logger.info(f"[EASAgent] Session: {session_id}, Message: {message}, File ID: {file_id}")

        file_content, file_name = None, None

        if file_id:
            try:
                file_stream = await agent_context.files.get_by_id(file_id)
                file_content = file_stream.read()
                metadata = await agent_context.files.get_metadata_by_id(file_id)
                file_name = metadata.get("file_name") or metadata.get("filename") or f"file_{file_id}"
                logger.info(f"[EASAgent] File received: {file_name}, size: {len(file_content)}")
            except Exception as fe:
                logger.error(f"[EASAgent] File load error: {str(fe)}")
                return {
                    "response": f"⚠️ Failed to load file: {str(fe)}",
                    "file_parsed": False,
                    "has_context": False,
                    "citations": []
                }

        workflow_input = WorkflowInput(
            message=message,
            session_id=session_id,
            file_content=file_content,
            file_name=file_name
        )

        result_event = await workflow.run(input=workflow_input)

        if hasattr(result_event, "result"):
            result_data = result_event.result
        else:
            result_data = result_event

        # ✅ Forward to MEVALAgent
        await session.send_message(Message(
            type="eas_output",
            sender_id="llamaindex_file_chat",
            recipient_id="mevalagent",
            data={
                "session_id": session_id,
                "user_id": agent_context.user_id,
                "summaries": {
                    "response": result_data.get("response"),
                    "citations": result_data.get("citations", [])
                },
                "file_name": file_name
            }
        ))

        return {
            "response": result_data.get("response", "No response generated."),
            "file_parsed": bool(file_content),
            "has_context": result_data.get("has_context", False),
            "citations": result_data.get("citations", []),
            "file_name": file_name
        }

    except Exception as e:
        logger.error(f"[EASAgent] Fatal error: {str(e)}")
        return {
            "response": f"❌ Unexpected error occurred: {str(e)}",
            "file_parsed": False,
            "has_context": False,
            "citations": []
        }

async def main():
    print(f"LlamaIndex File Chat Agent with token '{AGENT_JWT}' started")
    print("Agent capabilities:")
    print("- LlamaParse-powered document parsing (like original A2A samples)")
    print("- Supports PDF, DOCX, TXT, and other document formats")
    print("- Conversational Q&A about uploaded documents")
    print("- Multi-turn conversations with context retention")
    print("- Citation support for document references")
    print("- OpenAI integration for embeddings and chat")
    print("- Session management via genai-agentOS")
    
    # Check if LlamaParse is configured
    if not os.getenv("LLAMA_CLOUD_API_KEY"):
        print("⚠️  WARNING: LLAMA_CLOUD_API_KEY not set. Document parsing will use fallback method.")
        print("   Get your API key from: https://cloud.llamaindex.ai")
    elif not LlamaParse:
        print("⚠️  WARNING: llama-parse not installed. Install with: pip install llama-parse")
    else:
        print("✅ LlamaParse configured and ready for document parsing")
    
    await session.process_events()

if __name__ == "__main__":
    asyncio.run(main())