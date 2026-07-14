from abc import ABC, abstractmethod
from typing import BinaryIO, List

import docx
import pypdf


class DocumentPage:
    """Represents a single parsed page or layout unit of a document.
    
    Carries text content and location metadata for subsequent citation.
    """
    def __init__(self, text: str, page_number: int, section: str = "") -> None:
        self.text = text
        self.page_number = page_number
        self.section = section

    def __repr__(self) -> str:
        return f"<DocumentPage(page={self.page_number}, section='{self.section}', text_len={len(self.text)})>"


class BaseParser(ABC):
    """Abstract Base Class defining the file parser interface."""
    @abstractmethod
    def parse(self, file_content: BinaryIO, filename: str) -> List[DocumentPage]:
        """Parse raw file bytes into a list of structured document pages.
        
        Args:
            file_content: A binary file-like stream containing the document.
            filename: The name of the file being processed.
            
        Returns:
            List[DocumentPage]: List of pages with metadata.
        """
        pass


class TxtParser(BaseParser):
    """Parser for raw text files."""
    def parse(self, file_content: BinaryIO, filename: str) -> List[DocumentPage]:
        content = file_content.read().decode("utf-8", errors="replace")
        return [DocumentPage(text=content.strip(), page_number=1)]


class PDFParser(BaseParser):
    """Parser for PDF documents using pypdf."""
    def parse(self, file_content: BinaryIO, filename: str) -> List[DocumentPage]:
        reader = pypdf.PdfReader(file_content)
        pages = []
        for idx, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            pages.append(DocumentPage(text=text.strip(), page_number=idx + 1))
        return pages


class DocxParser(BaseParser):
    """Parser for Word files (.docx) using python-docx."""
    def parse(self, file_content: BinaryIO, filename: str) -> List[DocumentPage]:
        doc = docx.Document(file_content)
        paragraphs_text = []
        current_section = ""

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            # Simple section extraction: detect headings
            if para.style and para.style.name and para.style.name.startswith("Heading"):
                current_section = text
            paragraphs_text.append(text)

        full_text = "\n\n".join(paragraphs_text)
        return [DocumentPage(text=full_text, page_number=1, section=current_section)]
