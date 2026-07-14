import os
import json
from unittest.mock import patch, MagicMock

from scripts.run_eval import run_evaluation


@patch("scripts.run_eval.is_real_api_key_set", return_value=False)
def test_eval_script_runs_against_seed_dataset_without_error(mock_api_check: MagicMock) -> None:
    """Test that the evaluation script runs without raising errors and returns results."""
    # We patch vector store, embeddings and completions to run completely decoupled in test suite
    with patch("app.core.vector_store.QdrantVectorStore.search_similar", return_value=[]), \
         patch("qdrant_client.QdrantClient.scroll", return_value=([], None)), \
         patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents", return_value=[[0.1]*1024]), \
         patch("app.core.reranker.BgeReranker.rerank", side_effect=lambda q, ch: ch), \
         patch("app.core.llm_provider.MistralLlmProvider.generate_answer", return_value="not enough information"):
         
        summary = run_evaluation()
        
    assert isinstance(summary, dict)
    assert "timestamp" in summary
    assert "averages" in summary
    assert "details" in summary
    assert len(summary["details"]) == 10


@patch("scripts.run_eval.is_real_api_key_set", return_value=False)
def test_eval_scores_are_in_valid_range(mock_api_check: MagicMock) -> None:
    """Test that all average and item-level evaluation scores are within the expected [0, 1] range."""
    with patch("app.core.vector_store.QdrantVectorStore.search_similar", return_value=[]), \
         patch("qdrant_client.QdrantClient.scroll", return_value=([], None)), \
         patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents", return_value=[[0.1]*1024]), \
         patch("app.core.reranker.BgeReranker.rerank", side_effect=lambda q, ch: ch), \
         patch("app.core.llm_provider.MistralLlmProvider.generate_answer", return_value="not enough information"):
         
        summary = run_evaluation()

    # Check averages range
    averages = summary["averages"]
    for metric in ["faithfulness", "answer_relevance", "context_precision"]:
        assert 0.0 <= averages[metric] <= 1.0

    # Check details range
    for detail in summary["details"]:
        scores = detail["scores"]
        for metric in ["faithfulness", "answer_relevance", "context_precision"]:
            assert 0.0 <= scores[metric] <= 1.0


@patch("scripts.run_eval.is_real_api_key_set", return_value=False)
def test_results_file_written_with_expected_schema(mock_api_check: MagicMock) -> None:
    """Test that evaluation output files are successfully written and match the output JSON schema."""
    with patch("app.core.vector_store.QdrantVectorStore.search_similar", return_value=[]), \
         patch("qdrant_client.QdrantClient.scroll", return_value=([], None)), \
         patch("app.core.llm_provider.MistralEmbeddingProvider.embed_documents", return_value=[[0.1]*1024]), \
         patch("app.core.reranker.BgeReranker.rerank", side_effect=lambda q, ch: ch), \
         patch("app.core.llm_provider.MistralLlmProvider.generate_answer", return_value="not enough information"):
         
        summary = run_evaluation()

    # Locate output directory
    out_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../eval_results"))
    assert os.path.exists(out_dir)
    
    files = [f for f in os.listdir(out_dir) if f.endswith(".json")]
    assert len(files) > 0
    
    # Sort files by name to check the latest
    files.sort()
    latest_file = os.path.join(out_dir, files[-1])
    
    with open(latest_file, "r") as f:
        file_content = json.load(f)
        
    assert file_content["averages"] == summary["averages"]
    assert len(file_content["details"]) == len(summary["details"])
    
    # Cleanup for test run cleanliness
    os.remove(latest_file)
