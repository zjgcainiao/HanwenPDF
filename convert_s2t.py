#!/usr/bin/env python3
import re
import os
import sys
import logging
import argparse
from dataclasses import dataclass
from pathlib import Path
from opencc import OpenCC
from reportlab.lib.pagesizes import LETTER
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, ActionFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfgen import canvas

@dataclass(frozen=True)
class PDFConfig:
    """Centralized configuration for PDF layout and styles."""
    PROJECT_ROOT = Path(__file__).resolve().parent
    # Converter Settings
    CONVERSION_MODE: str = "s2twp"
    # Page Layout (72 points = 1 inch)
    PAGE_SIZE: tuple = LETTER
    MARGIN_LEFT: int = 72
    MARGIN_RIGHT: int = 72
    MARGIN_TOP: int = 72
    MARGIN_BOTTOM: int = 72  # Increased for footer room
    
    # Fonts
    FONT_NAME: str = "NotoSansTC"
    FONT_PATH: str = str(PROJECT_ROOT / "fonts" / "NotoSansTC-Regular.ttf")
    # Check if font exists on startup
    @classmethod
    def validate_font(cls):
        if not os.path.exists(cls.FONT_PATH):
            print(f"CRITICAL ERROR: Font not found at {cls.FONT_PATH}")
            print("Please ensure you have placed the font in the 'fonts/' folder.")
            return False
        return True
    # Text Styles
    TITLE_SIZE: int = 24
    TITLE_LEADING: int = 30
    CHAPTER_SIZE: int = 18
    CHAPTER_LEADING: int = 22
    BODY_SIZE: int = 12
    BODY_LEADING: int = 18
    FOOTER_SIZE: int = 9
    
    # Logic Spacing
    SPACE_AFTER_TITLE: int = 40
    SPACE_AFTER_CHAPTER: int = 20
    SPACE_BEFORE_CHAPTER: int = 20
    SPACE_AFTER_PARA: int = 6
    INDENT_SIZE: int = 24

class PageNumCanvas(canvas.Canvas):
    """Custom canvas to support 'Page X of Y' numbering."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # self.pages = []
        self._saved_page_states = []
        self._current_page_bookmarks=[]
    
    # record bookmark/outlines for later replay (two-pass)
    def bookmarkPage(self, key):
        # Instead of calling super(), save it for later
        self._current_page_bookmarks.append(('bookmark', key))
    
    def addOutlineEntry(self, title, key, level=0, closed=True):
        # Instead of calling super(), save it for later
        self._current_page_bookmarks.append(('outline', title, key, level, closed))

    def showPage(self):
        # capture only the current page's canvas state (NOT the whole growing history)
        page_state = dict(self.__dict__)
        # critical: remove recursive / irrelevant items
        page_state.pop("_saved_page_states", None)
        page_state.pop("pages", None)  # in case you used this name earlier
        # attach bookmarks for this page only
        page_state['_bookmarks'] = self._current_page_bookmarks
        self._saved_page_states.append(page_state)
        # reset per-page bookmark buffer
        self._current_page_bookmarks = []

        # self.pages.append(page_state)
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for page in self._saved_page_states:
            bookmarks = page.pop('_bookmarks', [])
            self.__dict__.update(page)
            # REPLAY the bookmarks and outline entries for THIS specific physical page
            for entry in bookmarks:
                if entry[0] == 'bookmark':
                    super().bookmarkPage(entry[1])
                elif entry[0] == 'outline':
                    super().addOutlineEntry(entry[1], entry[2], level=entry[3], closed=entry[4])
            if self._pageNumber > 1:  # Skip footer on Title Page
                self.draw_page_number(page_count)
            
            # Now the physical page is written with bookmarks attached
            super().showPage()

        super().save()

    def draw_page_number(self, page_count):
        self.setFont(PDFConfig.FONT_NAME, PDFConfig.FOOTER_SIZE)
        
        # 1. Draw a thin separator line
        # Logic: From Left Margin to Right Margin, 45 points from bottom
        self.setStrokeColorRGB(0.7, 0.7, 0.7) # Light Gray
        self.setLineWidth(0.5)
        self.line(
            PDFConfig.MARGIN_LEFT, 45, 
            PDFConfig.PAGE_SIZE[0] - PDFConfig.MARGIN_RIGHT, 45
        )
        
        # 2. Draw the Page X of Y text
        current_page = self._pageNumber - 1
        total_adjusted = page_count - 1
        page_text = f"Page {current_page} of {total_adjusted}"
        self.drawCentredString(PDFConfig.PAGE_SIZE[0] / 2, 30, page_text)
    
# --- 3. Custom Template for Table of Contents (Outline) ---
class OutlineDocTemplate(SimpleDocTemplate):
    """Subclass of SimpleDocTemplate to handle PDF sidebar bookmarks."""
    def afterFlowable(self, flowable):
        """This hook runs every time a Paragraph is placed on a page."""
        if isinstance(flowable, Paragraph) and hasattr(flowable, 'is_chapter'):
            # This marks the CURRENT page and CURRENT position as the target
            # Register the bookmark in the PDF Sidebar
            self.canv.bookmarkPage(flowable.chapter_key)
            self.canv.addOutlineEntry(
                flowable.chapter_title, 
                flowable.chapter_key, 
                level=0, 
                closed=True
            )

# simplifed chinese to traditional 
def convert_s2t_txt_to_pdf(txt_path: Path, output_folder: Path):
    
    # 1. Initialize OpenCC (s2t = Simplified to Traditional)
    cc = OpenCC(PDFConfig.CONVERSION_MODE)
    
    # 2. Setup Font (Essential for Chinese PDF support)
    if not Path(PDFConfig.FONT_PATH).exists():
        logging.error(f"Font not found at {PDFConfig.FONT_PATH}")
        return

    pdfmetrics.registerFont(TTFont(PDFConfig.FONT_NAME, PDFConfig.FONT_PATH))

    # 3. Read and Convert
    try:
        with open(txt_path, 'r', encoding='utf-8') as f:
            lines = [cc.convert(line.strip()) for line in f.readlines()]
    except Exception as e:
        logging.error(f"Failed to read file: {e}")
        return
    
    # 4. Create PDF using Platypus
    output_folder.mkdir(parents=True, exist_ok=True)
    new_file_name = cc.convert(txt_path.stem)
    pdf_path = output_folder / f"{new_file_name}_traditional.pdf"
    
    # Define the Document Template (Set to Letter)
    doc = OutlineDocTemplate(
        str(pdf_path),
        pagesize=PDFConfig.PAGE_SIZE,
        rightMargin=PDFConfig.MARGIN_RIGHT,
        leftMargin=PDFConfig.MARGIN_LEFT,
        topMargin=PDFConfig.MARGIN_TOP,
        bottomMargin=PDFConfig.MARGIN_BOTTOM,
        wordWrap='CJK'
    )
    
    # 5. Define Styles
    styles = getSampleStyleSheet()
    # Title Style (First line)
    title_style = ParagraphStyle(
        'TitleStyle',
        parent=styles['Normal'],
        fontName=PDFConfig.FONT_NAME,
        fontSize=PDFConfig.TITLE_SIZE,
        leading=PDFConfig.TITLE_LEADING,
        alignment=TA_CENTER,
        spaceAfter=PDFConfig.SPACE_AFTER_TITLE,
    )

    # Chapter Style (第X回)
    chapter_style = ParagraphStyle(
        'ChapterStyle',
        parent=styles['Normal'],
        fontName=PDFConfig.FONT_NAME,
        fontSize=PDFConfig.CHAPTER_SIZE,
        leading=PDFConfig.CHAPTER_LEADING,
        alignment=TA_CENTER,
        spaceBefore=PDFConfig.SPACE_BEFORE_CHAPTER,
        spaceAfter=PDFConfig.SPACE_AFTER_CHAPTER,
        wordWrap='CJK'
    )

    # Body Style
    body_style = ParagraphStyle(
        'BodyStyle',
        parent=styles['Normal'],
        fontName=PDFConfig.FONT_NAME,
        fontSize=PDFConfig.BODY_SIZE,
        leading=PDFConfig.BODY_LEADING,
        firstLineIndent=PDFConfig.INDENT_SIZE,  # Standard Chinese indentation
        wordWrap='CJK'
    )
    # 6. Build the "Story"
    story = []
    
    chapter_pattern = re.compile(r'^第[一二三四五六七八九十百千万\d]+回')
    first_chapter_found = False
    for i, line in enumerate(lines):
        if not line:
            continue
        # Mark the very top of the document as the Title
        if i==0:
            story.append(Paragraph(f"<b>{line}</b>", title_style))
            story.append(PageBreak())
            continue

        # Case B: Chapter Heading
        if chapter_pattern.match(line):
            # Only add a PageBreak if this is NOT the very first chapter
            if first_chapter_found:
                story.append(PageBreak())

            # 1. Create a unique key for this chapter
            chapter_key = f"chap_{i}"
            
            p = Paragraph(f"<b>{line}</b>", chapter_style)
            # Custom attributes used by OutlineDocTemplate.afterFlowable
            p.is_chapter = True
            p.chapter_title = line
            p.chapter_key = chapter_key
            story.append(p)
            first_chapter_found = True # Mark that we've started the book
            continue

        # case C: standard body text
        story.append(Paragraph(line,body_style))
        story.append(Spacer(1,PDFConfig.SPACE_AFTER_PARA))


    # 7. Generate the file
    doc.build(story,canvasmaker=PageNumCanvas)
    logging.info(f"Success! PDF saved to: {str(pdf_path.resolve())}")
    return str(pdf_path)
    
def main():
    # --- Configuration & Logging ---
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    parser = argparse.ArgumentParser(description="Convert Simplified Chinese TXT to Traditional Chinese PDF with proper formatting.")
    
    # Positional argument (Required)
    parser.add_argument("input", type=str, help="Path to the input .txt file")
    
    # Optional argument
    parser.add_argument("-o", "--output", type=str, default=".", help="Output folder (default: current directory)")

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        logging.error(f"File not found: {input_path}")
        sys.exit(1)
    if input_path.suffix.lower() !=".txt":
        logging.error(f"Can not process. Requires a .txt file as input")
        sys.exit(1)

    convert_s2t_txt_to_pdf(input_path, output_path)

if __name__ == "__main__":
    main()