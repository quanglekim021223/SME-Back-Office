"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";

import { downloadDocument, formatApiError } from "../../_lib/api-client";

export type OcrLayoutBlock = {
  id: string;
  text: string;
  pageNumber: number;
  boundingBox: number[] | null;
  confidence: number | null;
  pageWidth: number | null;
  pageHeight: number | null;
};

export type EvidenceFieldKind =
  | "invoice_number"
  | "supplier"
  | "customer"
  | "issue_date"
  | "due_date"
  | "total";

type SourceEvidencePreviewProps = {
  blocks: OcrLayoutBlock[];
  documentId: string | null;
  activeBlock: OcrLayoutBlock | null;
};

type SourceEvidenceRegionsProps = {
  blocks: OcrLayoutBlock[];
  documentType: string;
  activeBlock: OcrLayoutBlock | null;
  onSelect: (blockId: string) => void;
};

type SourceDocument = {
  contentType: string | null;
  fileName: string | null;
  url: string;
};

export function SourceEvidencePreview({
  blocks,
  documentId,
  activeBlock,
}: SourceEvidencePreviewProps) {
  const [source, setSource] = useState<SourceDocument | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(Boolean(documentId));

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    if (!documentId) {
      setSource(null);
      setLoadError("This review task has no linked source document.");
      setIsLoading(false);
      return;
    }

    const sourceDocumentId = documentId;

    async function loadSource() {
      setIsLoading(true);
      setLoadError(null);

      try {
        const downloaded = await downloadDocument(sourceDocumentId);
        objectUrl = URL.createObjectURL(downloaded.blob);
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          objectUrl = null;
          return;
        }
        setSource({
          contentType: downloaded.contentType,
          fileName: downloaded.fileName,
          url: objectUrl,
        });
      } catch (error) {
        if (!cancelled) {
          setSource(null);
          setLoadError(formatApiError(error));
        }
      } finally {
        if (!cancelled) {
          setIsLoading(false);
        }
      }
    }

    void loadSource();
    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [documentId]);

  const isImage = Boolean(source?.contentType?.startsWith("image/"));
  const overlayStyle = activeBlock
    ? buildOverlayStyle(activeBlock, blocks)
    : null;

  return (
    <div className="evidence-viewer-stage">
      {isLoading ? (
        <p className="evidence-viewer-message">Loading original document...</p>
      ) : loadError ? (
        <p className="evidence-viewer-message evidence-viewer-error">
          Source preview unavailable: {loadError}
        </p>
      ) : source && isImage ? (
        <div className="evidence-viewer-image-canvas">
          <img
            alt={source.fileName ?? "Original uploaded document"}
            className="evidence-viewer-image"
            src={source.url}
          />
          {overlayStyle ? (
            <span
              aria-label={`OCR region: ${activeBlock?.text}`}
              className="evidence-viewer-overlay"
              style={overlayStyle}
            />
          ) : null}
        </div>
      ) : source ? (
        <>
          <iframe
            className="evidence-viewer-document"
            src={source.url}
            title={source.fileName ?? "Original uploaded document"}
          />
          <p className="evidence-viewer-message">
            Visual overlays are available for image documents.
          </p>
        </>
      ) : null}
    </div>
  );
}

export function SourceEvidenceRegions({
  blocks,
  documentType,
  activeBlock,
  onSelect,
}: SourceEvidenceRegionsProps) {
  const activeRegionRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    activeRegionRef.current?.scrollIntoView({ block: "nearest" });
  }, [activeBlock?.id]);

  return (
    <div className="source-evidence-viewer">
      <div className="evidence-viewer-toolbar">
        <div className="evidence-viewer-metadata">
          <span>{documentType}</span>
          <strong>{blocks.length} OCR regions</strong>
        </div>
        {activeBlock ? (
          <span className="evidence-viewer-confidence">
            Confidence {formatConfidence(activeBlock.confidence)}
          </span>
        ) : null}
      </div>

      <div className="evidence-viewer-inspection">
        <p>
          {activeBlock
            ? `Selected evidence: ${activeBlock.text}`
            : "Select an invoice field or OCR region to inspect its source evidence."}
        </p>
        {blocks.length > 0 ? (
          <div className="evidence-viewer-region-list">
            {blocks.map((block) => (
              <button
                aria-pressed={activeBlock?.id === block.id}
                className={
                  activeBlock?.id === block.id
                    ? "evidence-viewer-region evidence-viewer-region-selected"
                    : "evidence-viewer-region"
                }
                key={block.id}
                onClick={() => onSelect(block.id)}
                ref={activeBlock?.id === block.id ? activeRegionRef : null}
                type="button"
              >
                <span>{block.text}</span>
                <small>
                  Page {block.pageNumber} | {formatConfidence(block.confidence)}
                </small>
              </button>
            ))}
          </div>
        ) : (
          <p className="evidence-viewer-message">
            OCR layout regions will appear for newly processed documents.
          </p>
        )}
      </div>
    </div>
  );
}

export function findMatchingBlock(
  blocks: OcrLayoutBlock[],
  value: string | null,
  fieldKind: EvidenceFieldKind | null = null,
) {
  if (!value) {
    return null;
  }

  const normalizedValue = normalizeText(value);
  if (!normalizedValue) {
    return null;
  }

  const candidates = blocks.map((block, index) => ({
    block,
    index,
    normalized: normalizeText(block.text),
  }));
  const exactMatches = candidates.filter(
    (candidate) => candidate.normalized === normalizedValue,
  );
  if (exactMatches.length > 0) {
    return selectBestCandidate(exactMatches, blocks, fieldKind);
  }

  const normalizedDate = normalizeDate(value);
  if (normalizedDate) {
    const dateMatches = candidates.filter(
      (candidate) => normalizeDate(candidate.block.text) === normalizedDate,
    );
    if (dateMatches.length > 0) {
      return selectBestCandidate(dateMatches, blocks, fieldKind);
    }
  }

  const normalizedAmount = normalizeAmount(value);
  if (normalizedAmount) {
    const amountMatches = candidates.filter(
      (candidate) => normalizeAmount(candidate.block.text) === normalizedAmount,
    );
    if (amountMatches.length > 0) {
      return selectBestCandidate(amountMatches, blocks, fieldKind);
    }
  }

  const compactValue = normalizeCompact(value);
  const compactMatches = candidates.filter(
    (candidate) => normalizeCompact(candidate.block.text) === compactValue,
  );
  if (compactMatches.length > 0) {
    return selectBestCandidate(compactMatches, blocks, fieldKind);
  }

  const partialMatches = candidates
    .filter(
      (candidate) =>
        candidate.normalized.length >= 4 &&
        (candidate.normalized.includes(normalizedValue) ||
          normalizedValue.includes(candidate.normalized)),
    )
    .sort((left, right) => right.normalized.length - left.normalized.length);

  return partialMatches.length > 0
    ? selectBestCandidate(partialMatches, blocks, fieldKind)
    : null;
}

type MatchCandidate = {
  block: OcrLayoutBlock;
  index: number;
  normalized: string;
};

function selectBestCandidate(
  candidates: MatchCandidate[],
  blocks: OcrLayoutBlock[],
  fieldKind: EvidenceFieldKind | null,
) {
  if (candidates.length === 1 || !fieldKind) {
    return candidates[0]?.block ?? null;
  }

  const anchors = getFieldAnchors(fieldKind);
  if (anchors.length === 0) {
    return candidates[0]?.block ?? null;
  }

  const anchorIndexes = blocks.flatMap((block, index) =>
    anchors.includes(normalizeText(block.text)) ? [index] : [],
  );
  const ranked = [...candidates].sort(
    (left, right) =>
      distanceFromPrecedingAnchor(left.index, anchorIndexes) -
      distanceFromPrecedingAnchor(right.index, anchorIndexes),
  );

  return ranked[0]?.block ?? null;
}

function getFieldAnchors(fieldKind: EvidenceFieldKind) {
  switch (fieldKind) {
    case "invoice_number":
      return ["invoice", "invoice no", "invoice number"];
    case "customer":
      return ["bill to", "customer", "client"];
    case "issue_date":
      return ["invoice date", "issue date", "date"];
    case "due_date":
      return ["due date", "payment due"];
    case "total":
      return ["total", "amount due", "balance due"];
    case "supplier":
      return [];
  }
}

function distanceFromPrecedingAnchor(index: number, anchorIndexes: number[]) {
  const distances = anchorIndexes
    .filter((anchorIndex) => anchorIndex < index)
    .map((anchorIndex) => index - anchorIndex);

  return distances.length > 0
    ? Math.min(...distances)
    : Number.MAX_SAFE_INTEGER;
}

function buildOverlayStyle(
  block: OcrLayoutBlock,
  blocks: OcrLayoutBlock[],
): CSSProperties | null {
  if (!block.boundingBox || block.boundingBox.length < 4) {
    return null;
  }

  const bounds = resolvePageBounds(block, blocks);
  if (!bounds) {
    return null;
  }

  const coordinates = block.boundingBox;
  const xValues = coordinates.filter((_, index) => index % 2 === 0);
  const yValues = coordinates.filter((_, index) => index % 2 === 1);
  const minX = Math.min(...xValues);
  const maxX = Math.max(...xValues);
  const minY = Math.min(...yValues);
  const maxY = Math.max(...yValues);

  if (!Number.isFinite(minX + maxX + minY + maxY)) {
    return null;
  }

  return {
    height: `${Math.max(1, ((maxY - minY) / bounds.height) * 100)}%`,
    left: `${Math.max(0, (minX / bounds.width) * 100)}%`,
    top: `${Math.max(0, (minY / bounds.height) * 100)}%`,
    width: `${Math.max(1, ((maxX - minX) / bounds.width) * 100)}%`,
  };
}

function resolvePageBounds(block: OcrLayoutBlock, blocks: OcrLayoutBlock[]) {
  if (block.pageWidth && block.pageHeight) {
    return { height: block.pageHeight, width: block.pageWidth };
  }

  const pageBlocks = blocks.filter(
    (candidate) =>
      candidate.pageNumber === block.pageNumber && candidate.boundingBox,
  );
  const coordinates = pageBlocks.flatMap(
    (candidate) => candidate.boundingBox ?? [],
  );
  const xValues = coordinates.filter((_, index) => index % 2 === 0);
  const yValues = coordinates.filter((_, index) => index % 2 === 1);
  const width = Math.max(...xValues);
  const height = Math.max(...yValues);

  return width > 0 && height > 0 ? { height, width } : null;
}

function formatConfidence(confidence: number | null) {
  return confidence === null
    ? "not reported"
    : `${Math.round(confidence * 100)}%`;
}

function normalizeText(value: string) {
  return value
    .toLocaleLowerCase()
    .replace(/[^a-z0-9.]+/g, " ")
    .trim();
}

function normalizeCompact(value: string) {
  return normalizeText(value).replace(/\s+/g, "");
}

function normalizeDate(value: string) {
  const match = value.trim().match(/^(\d{1,4})[-/.](\d{1,2})[-/.](\d{1,4})$/);
  if (!match) {
    return null;
  }

  const [, first, second, third] = match;
  const [year, month, day] =
    first.length === 4 ? [first, second, third] : [third, second, first];
  const monthNumber = Number(month);
  const dayNumber = Number(day);

  if (
    year.length !== 4 ||
    monthNumber < 1 ||
    monthNumber > 12 ||
    dayNumber < 1 ||
    dayNumber > 31
  ) {
    return null;
  }

  return `${year}-${monthNumber.toString().padStart(2, "0")}-${dayNumber
    .toString()
    .padStart(2, "0")}`;
}

function normalizeAmount(value: string) {
  if (normalizeDate(value)) {
    return null;
  }

  const normalized = value
    .toLocaleLowerCase()
    .replace(/\b(?:usd|eur|gbp|aud|cad|vnd)\b/g, "")
    .replace(/[$€£₫,\s]/g, "");

  if (!/^-?\d+(?:\.\d{1,2})?$/.test(normalized)) {
    return null;
  }

  const amount = Number(normalized);
  return Number.isFinite(amount) ? amount.toFixed(2) : null;
}
