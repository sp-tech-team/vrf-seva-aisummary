#!/usr/bin/env python3
"""
vrf_indexer.py: Script for indexing VRF data into Pinecone vector store.

This script processes VRF (Volunteer Request Form) data and creates embeddings
for storage in Pinecone, enabling semantic search capabilities.

Usage:
    python vrf_indexer.py --vrf_data_cleaned_out_csv=path/to/cleaned.csv --verbose
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import argparse
import logging
import os
import pandas as pd

import ssl
import urllib3

# Disable SSL warnings and verification for corporate proxies
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
ssl._create_default_https_context = ssl._create_unverified_context
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''

from preprocessing.vrf_data import VrfData
from batch_allocator.pinecone_utils import get_pinecone_index, clear_index

from pinecone import Pinecone
from llama_index.vector_stores.pinecone import PineconeVectorStore
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI
from llama_index.core import Settings
from llama_index.core.schema import TextNode
from dotenv import load_dotenv
load_dotenv()


def index_parse_args() -> argparse.Namespace:
    """Parses command-line arguments.

    Returns:
        A namespace with parsed arguments.
    """
    parser = argparse.ArgumentParser(
        description="Process VRF data and create Pinecone vector store index."
    )

    parser.add_argument(
        "--vrf_data_raw_csv",
        default='data/vrf_data_raw.csv',
        help="Path to the raw VRF csv file.",
    )

    parser.add_argument(
        "--vrf_data_cleaned_out_csv",
        default='data/cleaned_csv.csv',
        help="Path to the cleaned VRF csv file.",
    )

    parser.add_argument(
        "--generic_jobs_csv",
        default='data/generic_jobs.csv',
        help="Path to the generic jobs csv file.",
    )

    parser.add_argument(
        "--pinecone_index_name",
        default='vrf-test-local',
        help="Name of the Pinecone index to use.",
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        dest='verbose',
        help="Enable verbose logging. (default is disabled)"
    )

    return parser.parse_args()


def create_index_nodes(vrf_db_df: pd.DataFrame) -> list[TextNode]:
    """
    Create index nodes from the VRF training data.
    
    Args:
        vrf_db_df: DataFrame containing VRF information with summary column.
    
    Returns:
        List of TextNode objects ready for embedding and indexing.
    """
    nodes = []
    for i, (_, row) in enumerate(vrf_db_df.iterrows()):
        if not row["summary"]:
            continue
        
        node = TextNode(
            text=row["summary"],
            id_=str(i),
            metadata={
                "Job Title": row["Job Title"],
                "Request Name": row["Request Name"],
                "Department": row["Department"]
            }
        )
        nodes.append(node)
    
    return nodes


def main() -> None:
    """Main entry point of the script."""
    args = index_parse_args()

    # Configure logging
    log_level = logging.INFO
    logging.basicConfig(
        level=log_level, 
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    if not args.verbose:
        logging.disable(logging.CRITICAL)

    logging.info("VRF Indexer script started.")
    print(f"Reading cleaned VRF data from: {args.vrf_data_cleaned_out_csv}", flush=True)
    print(f"Reading generic jobs from: {args.generic_jobs_csv}", flush=True)

    # Setup LLM and Embeddings
    llm = OpenAI(temperature=0, model_name="gpt-4o", max_tokens=4000)
    embedding_model = OpenAIEmbedding()
    Settings.llm = llm
    Settings.embed_model = embedding_model

    print("Creating Vector Store Index...", flush=True)
    
    # Load and process VRF data
    vrf_clean_df = pd.read_csv(args.vrf_data_cleaned_out_csv)
    generic_jobs_df = pd.read_csv(args.generic_jobs_csv)
    
    print(f"Loaded {len(vrf_clean_df)} cleaned VRF records", flush=True)
    print(f"Loaded {len(generic_jobs_df)} generic job records", flush=True)
    
    # Create VRF info dataframe with summaries
    vrf_data = VrfData(vrf_clean_df, generic_jobs_df)
    vrf_info_df = vrf_data.create_vrf_info_df()
    
    print(f"Created {len(vrf_info_df)} total records for indexing", flush=True)
    
    # Create nodes and generate embeddings
    nodes = create_index_nodes(vrf_info_df)
    print(f"Created {len(nodes)} text nodes", flush=True)
    
    print("Generating embeddings (this may take a while)...", flush=True)
    for i, node in enumerate(nodes):
        if (i + 1) % 50 == 0:
            print(f"  Generated embeddings for {i + 1}/{len(nodes)} nodes", flush=True)
        node.embedding = embedding_model.get_text_embedding(node.get_text())
    
    print("All embeddings generated successfully", flush=True)
    
    # Connect to Pinecone and create/clear index
    pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
    index = get_pinecone_index(
        args.pinecone_index_name, 
        pc, 
        create_if_not_exists=True
    )
    
    print(f"Connected to Pinecone index: {args.pinecone_index_name}", flush=True)
    
    # Clear existing data and add new nodes
    clear_index(index)
    print("Cleared existing index data", flush=True)
    
    vector_store = PineconeVectorStore(index)
    vector_store.add(nodes)
    
    print(f"Successfully added {len(nodes)} vectors to Pinecone index", flush=True)
    logging.info("VRF Indexer script finished successfully.")


if __name__ == "__main__":
    main()