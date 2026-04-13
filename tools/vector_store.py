"""
tools/vector_store.py

Vector store for RAG (Retrieval-Augmented Generation) across:
  - NVIDIA developer documentation
  - Resolved support tickets
  - Community threads

Uses ChromaDB running locally — no external service required.
Embeddings are generated via the sentence-transformers library.

Features:
  - Index documents from any source (docs, tickets, threads)
  - Semantic search across all indexed content
  - Source-tagged results (nvidia_docs | resolved_ticket | community)
  - Per-founder search context (filters by domain relevance)
  - Persistent storage — survives restarts

Usage:
    from tools.vector_store import VectorStore

    vs = VectorStore()

    # Index a document
    vs.index(
        doc_id="nim-on-premise-guide",
        content="Self-hosted NIM containers run inside your security perimeter...",
        source="nvidia_docs",
        metadata={"title": "NIM On-Premise Deployment Guide", "url": "https://..."}
    )

    # Search
    results = vs.search("How do I configure NIM for HIPAA compliance?", n=3)
    for r in results:
        print(r["source"], r["content"][:200])

    # Search filtered by source
    doc_results = vs.search("federated learning", source_filter="nvidia_docs")
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

CHROMA_DIR     = Path("outputs/chroma_db")
COLLECTION_NAME = "inception_knowledge"
DEFAULT_N      = 5

# Source tags — used for filtering and UI display
SOURCE_NVIDIA_DOCS     = "nvidia_docs"
SOURCE_RESOLVED_TICKET = "resolved_ticket"
SOURCE_COMMUNITY       = "community"
VALID_SOURCES          = {SOURCE_NVIDIA_DOCS, SOURCE_RESOLVED_TICKET, SOURCE_COMMUNITY}

# Seed documents — indexed on first run
# These give Aria immediate knowledge of core NVIDIA Inception topics
SEED_DOCUMENTS = [
    {
        "doc_id":  "nim-on-premise-overview",
        "content": (
            "NVIDIA NIM (NVIDIA Inference Microservices) can be self-hosted inside a customer's "
            "own security perimeter. Self-hosted NIM containers run on the customer's infrastructure "
            "and patient or sensitive data never egresses to an external server. This makes NIM "
            "on-premise the recommended architecture for HIPAA-compliant healthcare AI deployments. "
            "The API surface is identical to cloud NIM — application code does not change when "
            "switching from cloud to on-premise deployment."
        ),
        "source":   SOURCE_NVIDIA_DOCS,
        "metadata": {"title": "NIM On-Premise Deployment Overview", "domain": "healthcare"}
    },
    {
        "doc_id":  "nvidia-flare-federated-learning",
        "content": (
            "NVIDIA FLARE (Federated Learning Application Runtime Environment) enables training "
            "AI models across multiple sites without sharing raw data. Each site trains locally "
            "and only model updates — not patient data — are shared. This makes FLARE the "
            "standard architecture for multi-hospital AI deployments where HIPAA compliance "
            "requires data to remain on-premise. The model improves with every site that joins "
            "the federated network, creating a data flywheel that is architecturally defensible."
        ),
        "source":   SOURCE_NVIDIA_DOCS,
        "metadata": {"title": "NVIDIA FLARE — Federated Learning", "domain": "healthcare"}
    },
    {
        "doc_id":  "monai-clinical-imaging",
        "content": (
            "MONAI (Medical Open Network for AI) is an open-source framework built specifically "
            "for medical imaging AI. It provides pre-built models for radiology tasks including "
            "anomaly detection, segmentation, and classification. MONAI integrates natively with "
            "NVIDIA Clara and NIM. It speaks the clinical validation language that hospital "
            "procurement teams and radiologists require, including DICOM support and clinical "
            "benchmark standards. MONAI significantly reduces development time for founders "
            "building medical imaging products."
        ),
        "source":   SOURCE_NVIDIA_DOCS,
        "metadata": {"title": "MONAI for Clinical Imaging AI", "domain": "healthcare"}
    },
    {
        "doc_id":  "tao-toolkit-edge-ai",
        "content": (
            "NVIDIA TAO Toolkit enables transfer learning from NVIDIA's pre-trained models. "
            "Founders can fine-tune foundation models on their own domain-specific datasets "
            "without training from scratch. TAO supports model optimization for edge deployment "
            "including INT8 quantization for Jetson hardware. The toolkit integrates with "
            "NVIDIA Jetson Orin for real-time inference at the edge. TAO is the recommended "
            "path for precision agriculture, construction AI, and robotics founders who need "
            "production-grade models on constrained hardware."
        ),
        "source":   SOURCE_NVIDIA_DOCS,
        "metadata": {"title": "TAO Toolkit — Transfer Learning and Edge AI", "domain": "edge"}
    },
    {
        "doc_id":  "jetson-orin-deployment",
        "content": (
            "NVIDIA Jetson Orin NX is the recommended edge AI module for drone, robotics, and "
            "embedded system deployments. It supports NIM-optimized inference models and "
            "achieves sub-100ms inference latency on INT8-quantized models at 12-15W power "
            "envelope. Jetson Orin NX hardware cost is approximately $500-800 per unit. "
            "It is the primary edge compute platform for NVIDIA Inception founders building "
            "drone-based inspection, agricultural AI, and real-time construction monitoring."
        ),
        "source":   SOURCE_NVIDIA_DOCS,
        "metadata": {"title": "Jetson Orin NX — Edge Deployment", "domain": "edge"}
    },
    {
        "doc_id":  "inception-benefits-overview",
        "content": (
            "NVIDIA Inception program benefits include: Google Cloud credits ($350,000) for "
            "DGX Cloud training infrastructure, Anthropic Claude API credits ($1,000,000) for "
            "AI-powered application development, AWS Activate credits ($100,000), and free "
            "access to NVIDIA Deep Learning Institute courses. Benefits are available immediately "
            "upon acceptance and must be activated through the Inception portal. Founders who "
            "activate credits in the first 30 days have significantly higher milestone completion "
            "rates than those who delay activation."
        ),
        "source":   SOURCE_NVIDIA_DOCS,
        "metadata": {"title": "Inception Program Benefits", "domain": "program"}
    },
    {
        "doc_id":  "resolved-ticket-nim-gke-egress",
        "content": (
            "Issue: NIM egress policy sequencing on GKE node pool for HIPAA compliance. "
            "Resolution: The NetworkPolicy deny-all must be applied BEFORE the NIM pod starts. "
            "Apply at namespace level, not node pool level. Namespace-level policies are what "
            "HIPAA compliance auditors verify. Node pool policies handle performance isolation "
            "but are not the compliance layer. You can have both — namespace for compliance "
            "documentation, node pool for performance. Sequence: 1) Create namespace, "
            "2) Apply deny-all NetworkPolicy, 3) Add NIM pod ingress/egress exceptions, "
            "4) Deploy NIM containers."
        ),
        "source":   SOURCE_RESOLVED_TICKET,
        "metadata": {"title": "NIM GKE Egress Policy Sequencing", "domain": "healthcare"}
    },
    {
        "doc_id":  "resolved-ticket-tao-subset-training",
        "content": (
            "Issue: TAO fine-tuning accuracy degrading on full dataset. "
            "Resolution: Stop trying to achieve perfection on the full dataset at once. "
            "Split into domain-specific subsets and fine-tune sequentially. For crop disease "
            "detection: subset by disease type first, then by crop variety, then by lighting "
            "condition. Each subset produces a specialized checkpoint. Final model is assembled "
            "from best checkpoints per category. This approach improved accuracy from 76% to "
            "91% on a 40,000 image agricultural dataset in under 2 weeks."
        ),
        "source":   SOURCE_RESOLVED_TICKET,
        "metadata": {"title": "TAO Fine-Tuning with Domain Subsets", "domain": "edge"}
    },
    {
        "doc_id":  "community-flare-setup",
        "content": (
            "Community thread: NVIDIA FLARE federated learning setup that actually worked. "
            "Key insight: start with 2 sites before scaling to N sites. The FLARE aggregation "
            "server should run on DGX Cloud, not on a local machine. Site clients connect "
            "outbound only — no inbound ports required, which simplifies hospital firewall "
            "configuration significantly. Use FedAvg aggregation for medical imaging tasks. "
            "Model convergence with 2 sites takes approximately 3x longer than single-site "
            "training but produces a more generalizable model."
        ),
        "source":   SOURCE_COMMUNITY,
        "metadata": {"title": "FLARE Federated Setup — Community Thread", "domain": "healthcare"}
    },
    {
        "doc_id":  "community-riva-clinical-asr",
        "content": (
            "Community thread: Riva ASR for clinical dictation — reducing word error rate. "
            "Key insight: pre-filter audio for background noise before submission to Riva. "
            "Clinical environments have significant ambient noise from monitors, PA systems, "
            "and HVAC. A simple bandpass filter targeting 80-8000Hz speech frequencies "
            "reduced WER by 18% on clinical dictation tasks. Fine-tune Riva on medical "
            "terminology specifically — generic ASR models underperform on clinical vocabulary "
            "by 15-25% WER. Use NeMo for the fine-tuning pipeline."
        ),
        "source":   SOURCE_COMMUNITY,
        "metadata": {"title": "Riva Clinical ASR — WER Reduction", "domain": "nlp"}
    },
]


# ── VectorStore ───────────────────────────────────────────────────────────────

class VectorStore:
    """
    ChromaDB-backed vector store for semantic search across
    NVIDIA docs, resolved tickets, and community threads.

    Falls back to keyword search if ChromaDB is not installed.
    """

    def __init__(self, persist_dir: Path = CHROMA_DIR):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._collection = None
        self._documents  = []   # In-memory fallback store
        self._chroma_available = self._init_chroma()

        # Seed with core NVIDIA knowledge on first run
        if not self._is_seeded():
            self._seed()

    # ── Indexing ──────────────────────────────────────────────────────────────

    def index(
        self,
        doc_id:   str,
        content:  str,
        source:   str,
        metadata: Optional[dict] = None,
    ) -> None:
        """
        Index a document for semantic search.

        Args:
            doc_id:   Unique identifier for this document.
            content:  The text content to index and search.
            source:   One of: nvidia_docs | resolved_ticket | community
            metadata: Optional dict with title, url, domain, etc.
        """
        if source not in VALID_SOURCES:
            raise ValueError(f"source must be one of {VALID_SOURCES}, got '{source}'")

        meta = metadata or {}
        meta["source"]    = source
        meta["indexed_at"] = datetime.now().isoformat()

        if self._chroma_available and self._collection:
            # Check if doc already exists and update
            try:
                self._collection.upsert(
                    ids=[doc_id],
                    documents=[content],
                    metadatas=[meta],
                )
            except Exception as e:
                print(f"[VectorStore] ChromaDB upsert failed: {e}")
                self._index_fallback(doc_id, content, source, meta)
        else:
            self._index_fallback(doc_id, content, source, meta)

    def index_batch(self, documents: list[dict]) -> int:
        """
        Index multiple documents at once.
        Each dict must have: doc_id, content, source.
        Optional: metadata.
        Returns count of successfully indexed documents.
        """
        count = 0
        for doc in documents:
            try:
                self.index(
                    doc_id=doc["doc_id"],
                    content=doc["content"],
                    source=doc["source"],
                    metadata=doc.get("metadata"),
                )
                count += 1
            except Exception as e:
                print(f"[VectorStore] Failed to index {doc.get('doc_id')}: {e}")
        return count

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query:         str,
        n:             int = DEFAULT_N,
        source_filter: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic search across indexed documents.

        Args:
            query:         The search query string.
            n:             Number of results to return.
            source_filter: If set, only return results from this source.

        Returns:
            List of result dicts, each with:
                - doc_id, content, source, metadata, score
        """
        if self._chroma_available and self._collection:
            return self._search_chroma(query, n, source_filter)
        else:
            return self._search_fallback(query, n, source_filter)

    def search_for_founder(
        self,
        query:   str,
        founder: dict,
        n:       int = DEFAULT_N,
    ) -> list[dict]:
        """
        Search with founder context — boosts results relevant to the
        founder's domain, compliance requirements, and NVIDIA stack.
        """
        # Enrich the query with founder context
        domain      = founder.get("domain", "")
        compliance  = " ".join(founder.get("compliance_requirements", []))
        tools       = " ".join(founder.get("nvidia_tools", []))

        enriched_query = f"{query} {domain} {compliance} {tools}".strip()
        return self.search(enriched_query, n=n)

    # ── Stats ─────────────────────────────────────────────────────────────────

    def count(self, source_filter: Optional[str] = None) -> int:
        """Returns the number of indexed documents."""
        if self._chroma_available and self._collection:
            try:
                if source_filter:
                    results = self._collection.get(
                        where={"source": source_filter}
                    )
                    return len(results["ids"])
                return self._collection.count()
            except Exception:
                pass
        docs = self._documents
        if source_filter:
            docs = [d for d in docs if d["source"] == source_filter]
        return len(docs)

    def stats(self) -> dict:
        """Returns a summary of what's indexed."""
        return {
            "total":          self.count(),
            "nvidia_docs":    self.count(SOURCE_NVIDIA_DOCS),
            "resolved_tickets": self.count(SOURCE_RESOLVED_TICKET),
            "community":      self.count(SOURCE_COMMUNITY),
            "backend":        "chromadb" if self._chroma_available else "keyword_fallback",
        }

    # ── ChromaDB backend ──────────────────────────────────────────────────────

    def _init_chroma(self) -> bool:
        """Initialize ChromaDB. Returns True if successful."""
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(self.persist_dir))
            self._collection = client.get_or_create_collection(
                name=COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"}
            )
            return True
        except ImportError:
            print("[VectorStore] ChromaDB not installed. Using keyword fallback.")
            print("[VectorStore] Install with: pip install chromadb")
            return False
        except Exception as e:
            print(f"[VectorStore] ChromaDB init failed: {e}. Using keyword fallback.")
            return False

    def _search_chroma(
        self,
        query:         str,
        n:             int,
        source_filter: Optional[str],
    ) -> list[dict]:
        """Search using ChromaDB's vector similarity."""
        try:
            where = {"source": source_filter} if source_filter else None
            results = self._collection.query(
                query_texts=[query],
                n_results=min(n, self._collection.count() or 1),
                where=where,
            )

            output = []
            if not results["ids"] or not results["ids"][0]:
                return []

            for i, doc_id in enumerate(results["ids"][0]):
                output.append({
                    "doc_id":   doc_id,
                    "content":  results["documents"][0][i],
                    "source":   results["metadatas"][0][i].get("source", "unknown"),
                    "metadata": results["metadatas"][0][i],
                    "score":    1 - (results["distances"][0][i] if results.get("distances") else 0),
                })
            return output

        except Exception as e:
            print(f"[VectorStore] ChromaDB search failed: {e}. Falling back to keyword.")
            return self._search_fallback(query, n, source_filter)

    # ── Keyword fallback ──────────────────────────────────────────────────────

    def _index_fallback(
        self, doc_id: str, content: str, source: str, metadata: dict
    ) -> None:
        """Store document in memory for keyword search."""
        # Remove existing doc with same id
        self._documents = [d for d in self._documents if d["doc_id"] != doc_id]
        self._documents.append({
            "doc_id":   doc_id,
            "content":  content,
            "source":   source,
            "metadata": metadata,
        })

    def _search_fallback(
        self,
        query:         str,
        n:             int,
        source_filter: Optional[str],
    ) -> list[dict]:
        """
        Simple keyword search as fallback when ChromaDB is unavailable.
        Scores documents by number of query terms found.
        """
        query_terms = query.lower().split()
        docs = self._documents

        if source_filter:
            docs = [d for d in docs if d["source"] == source_filter]

        scored = []
        for doc in docs:
            text = doc["content"].lower()
            score = sum(1 for term in query_terms if term in text)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)

        return [
            {
                "doc_id":   doc["doc_id"],
                "content":  doc["content"],
                "source":   doc["source"],
                "metadata": doc["metadata"],
                "score":    score / max(len(query_terms), 1),
            }
            for score, doc in scored[:n]
        ]

    # ── Seeding ───────────────────────────────────────────────────────────────

    def _is_seeded(self) -> bool:
        """Returns True if the store has already been seeded."""
        seed_flag = self.persist_dir / ".seeded"
        return seed_flag.exists()

    def _seed(self) -> None:
        """Index the core NVIDIA knowledge base on first run."""
        print("[VectorStore] Seeding knowledge base...")
        count = self.index_batch(SEED_DOCUMENTS)
        print(f"[VectorStore] Seeded {count} documents.")

        # Write seed flag
        seed_flag = self.persist_dir / ".seeded"
        seed_flag.write_text(datetime.now().isoformat())


# ── Module-level singleton ────────────────────────────────────────────────────

try:
    vs = VectorStore()
except Exception as e:
    print(f"[VectorStore] Failed to initialize: {e}")
    vs = None