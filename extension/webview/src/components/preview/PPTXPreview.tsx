/**
 * PPTXPreview Component
 *
 * Rich preview for PPTX files showing slide outline with extracted content.
 * Reference: docs/open-source-fit-and-provider-strategy.md §7.7
 */

import React, { useState } from "react";

export interface PPTXSlide {
  index: number;
  title: string;
  notes: string;
  images: string[];
  content: string;
}

export interface PPTXPreviewProps {
  /** Markdown content from MarkItDown */
  markdown: string;
  /** File name for title display */
  filename?: string;
}

/** Parse MarkItDown markdown into slide structure */
function parseSlides(markdown: string): PPTXSlide[] {
  const slides: PPTXSlide[] = [];
  const slidePattern = /# Slide (\d+)\s*\n([\s\S]*?)(?=# Slide |\n# |\n## |\n$|$)/g;

  let match;
  while ((match = slidePattern.exec(markdown)) !== null) {
    const index = parseInt(match[1], 10);
    const content = match[2].trim();

    // Extract title from first heading or first line
    let title = `Slide ${index}`;
    const titleMatch = content.match(/^#\s+(.+)$/m) || content.match(/^([^\n]+)$/m);
    if (titleMatch) {
      title = titleMatch[1].replace(/^#+\s*/, "").trim();
    }

    // Extract notes (text after --- or in italic)
    const notesMatch = content.match(/---\s*\n([\s\S]*)$/) || content.match(/_([\s\S]*?)_$/m);
    const notes = notesMatch ? notesMatch[1].trim() : "";

    // Extract image references
    const images: string[] = [];
    const imageMatches = content.matchAll(/!\[.*?\]\((.*?)\)/g);
    for (const img of imageMatches) {
      images.push(img[1]);
    }

    // Clean content for display
    const cleanContent = content
      .replace(/!\[.*?\]\(.*?\)/g, "[Image]")
      .replace(/^#.*$/gm, "")
      .replace(/^--.*$/gm, "")
      .trim();

    slides.push({ index, title, notes, images, content: cleanContent });
  }

  // Fallback: if no slide pattern matched, treat entire content as one slide
  if (slides.length === 0 && markdown.trim()) {
    slides.push({
      index: 1,
      title: "Presentation",
      notes: "",
      images: [],
      content: markdown.trim(),
    });
  }

  return slides;
}

export const PPTXPreview: React.FC<PPTXPreviewProps> = ({
  markdown,
  filename = "presentation",
}) => {
  const [selectedSlide, setSelectedSlide] = useState<number>(0);
  const slides = parseSlides(markdown);

  if (slides.length === 0) {
    return (
      <div className="trainer-pptx-preview">
        <div className="pptx-header">
          <span className="pptx-icon">PPT</span>
          <span className="pptx-filename">{filename}</span>
        </div>
        <div className="pptx-empty">No content available</div>
      </div>
    );
  }

  const currentSlide = slides[selectedSlide];

  return (
    <div className="trainer-pptx-preview">
      <div className="pptx-header">
        <div className="pptx-title">
          <span className="pptx-icon">PPT</span>
          <span className="pptx-filename">{filename}</span>
        </div>
        <div className="pptx-stats">
          <span className="pptx-stat">{slides.length} slides</span>
        </div>
      </div>

      <div className="pptx-content">
        <div className="pptx-sidebar">
          <div className="pptx-slide-list">
            {slides.map((slide, idx) => (
              <button
                key={slide.index}
                className={`pptx-slide-item ${idx === selectedSlide ? "active" : ""}`}
                onClick={() => setSelectedSlide(idx)}
              >
                <span className="slide-number">{slide.index}</span>
                <span className="slide-title">{slide.title}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="pptx-main">
          <div className="pptx-slide-header">
            <span className="slide-indicator">Slide {currentSlide.index} of {slides.length}</span>
            <span className="slide-title-main">{currentSlide.title}</span>
          </div>

          <div className="pptx-slide-content">
            {currentSlide.images.length > 0 && (
              <div className="pptx-images">
                <span className="pptx-images-label">Images in this slide:</span>
                <div className="pptx-image-list">
                  {currentSlide.images.map((img, idx) => (
                    <span key={idx} className="pptx-image-badge">
                      {img.split("/").pop()?.split("\\").pop() || `Image ${idx + 1}`}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div className="pptx-text">
              {currentSlide.content.split("\n\n").filter(Boolean).map((para, idx) => (
                <p key={idx}>{para}</p>
              ))}
            </div>

            {currentSlide.notes && (
              <div className="pptx-notes">
                <span className="pptx-notes-label">Notes:</span>
                <p>{currentSlide.notes}</p>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
