from pathlib import Path

import pytest

from fzastro_ai.knowledge_library import DocumentKnowledgeLibrary


def test_document_knowledge_library_imports_without_gui_stack():
    assert DocumentKnowledgeLibrary.__name__ == "DocumentKnowledgeLibrary"


def test_document_knowledge_library_imports_and_searches_text_file(tmp_path):
    database_path = tmp_path / "knowledge.sqlite3"
    asset_dir = tmp_path / "assets"
    document_path = tmp_path / "m31_notes.txt"
    document_path.write_text(
        "Andromeda M31 imaging notes. Use short sub-exposures for the bright core.\n"
        "The outer dust lanes benefit from long total integration time.\n",
        encoding="utf-8",
    )

    library = DocumentKnowledgeLibrary(database_path, asset_directory=asset_dir)
    result = library.import_document(document_path)

    assert result["status"] == "imported"
    assert result["name"] == "m31_notes.txt"
    assert result["chunk_count"] >= 1
    assert result["visual_count"] == 0

    documents = library.list_documents()
    assert [document["name"] for document in documents] == ["m31_notes.txt"]

    results = library.search("M31 bright core", limit=3)
    assert results
    assert results[0]["document_name"] == "m31_notes.txt"
    assert "bright core" in results[0]["content"].lower()


def test_document_knowledge_library_duplicate_import_is_reported(tmp_path):
    database_path = tmp_path / "knowledge.sqlite3"
    document_path = tmp_path / "duplicate.txt"
    document_path.write_text(
        "Repeated calibration note about flat frames.", encoding="utf-8"
    )

    library = DocumentKnowledgeLibrary(
        database_path, asset_directory=tmp_path / "assets"
    )
    first = library.import_document(document_path)
    second = library.import_document(document_path)

    assert first["status"] == "imported"
    assert second["status"] == "duplicate"
    assert second["id"] == first["id"]
    assert len(library.list_documents()) == 1


def test_document_knowledge_library_build_context_bundle_for_text_file(tmp_path):
    library = DocumentKnowledgeLibrary(
        tmp_path / "knowledge.sqlite3", asset_directory=tmp_path / "assets"
    )
    document_path = tmp_path / "filters.txt"
    document_path.write_text(
        "Narrowband filter notes: H-alpha frames improve nebula contrast.\n",
        encoding="utf-8",
    )
    library.import_document(document_path)

    knowledge_context, visual_files, results = library.build_context_bundle(
        "What do the filter notes say about H-alpha?"
    )

    assert knowledge_context
    assert "H-alpha" in knowledge_context
    assert visual_files == []
    assert results


@pytest.mark.parametrize(
    "query",
    [
        "What documents are in my knowledge library?",
        "Which documents are inside the knowledge library?",
        "List the documents in our document library",
        "Show available documents",
        "What books do we have?",
    ],
)
def test_document_inventory_requests_match_common_toolbar_prompts(query):
    assert DocumentKnowledgeLibrary.query_requests_document_inventory(query)


def test_document_inventory_does_not_catch_selected_document_questions():
    query = (
        "Answer using only this imported document: Yearbook_of_Astronomy_2023.pdf\n\n"
        "Question: what is this book?"
    )

    assert not DocumentKnowledgeLibrary.query_requests_document_inventory(query)


def test_selected_document_overview_question_is_document_brief_request():
    query = (
        "Answer using only this imported document: Yearbook_of_Astronomy_2023.pdf\n\n"
        "Question: what is this book?"
    )

    assert DocumentKnowledgeLibrary.query_requests_document_brief(query)


def test_document_inventory_does_not_catch_selected_document_questions_by_number():
    query = "Answer using only this document: 1\n\nQuestion: what books are mentioned?"

    assert not DocumentKnowledgeLibrary.query_requests_document_inventory(query)


def test_document_inventory_response_uses_database_state(tmp_path):
    library = DocumentKnowledgeLibrary(
        tmp_path / "knowledge.sqlite3", asset_directory=tmp_path / "assets"
    )
    document_path = tmp_path / "Yearbook_of_Astronomy_2025.txt"
    document_path.write_text("January sky notes. Mars at opposition.", encoding="utf-8")
    library.import_document(document_path)

    response = library.format_document_inventory_response()

    assert "Yearbook_of_Astronomy_2025.txt" in response
    assert "Astrophotography Manual" not in response
    assert "1" in response


def test_document_knowledge_clear_removes_orphaned_assets_and_returns_storage_stats(
    tmp_path,
):
    database_path = tmp_path / "knowledge.sqlite3"
    asset_dir = tmp_path / "assets"
    document_path = tmp_path / "clear_me.txt"
    document_path.write_text("Clear-library compaction test text.", encoding="utf-8")

    library = DocumentKnowledgeLibrary(database_path, asset_directory=asset_dir)
    library.import_document(document_path)

    orphan_dir = asset_dir / "orphan"
    orphan_dir.mkdir(parents=True)
    (orphan_dir / "leftover.bin").write_bytes(b"x" * 1024)

    result = library.clear()

    assert result["removed_documents"] == 1
    assert result["asset_size_bytes"] == 0
    assert not any(asset_dir.iterdir())
    assert library.list_documents() == []


def test_document_knowledge_compact_storage_reports_reclaimed_shape(tmp_path):
    database_path = tmp_path / "knowledge.sqlite3"
    asset_dir = tmp_path / "assets"
    document_path = tmp_path / "compact_me.txt"
    document_path.write_text("Compact storage test text." * 100, encoding="utf-8")

    library = DocumentKnowledgeLibrary(database_path, asset_directory=asset_dir)
    library.import_document(document_path)
    library.clear()

    result = library.compact_storage()

    assert "before_total_size_bytes" in result
    assert "reclaimed_bytes" in result
    assert result["document_count"] == 0
    assert result["chunk_count"] == 0
    assert result["visual_count"] == 0


def test_document_brief_request_resolves_inventory_number_and_returns_context(tmp_path):
    library = DocumentKnowledgeLibrary(
        tmp_path / "knowledge.sqlite3", asset_directory=tmp_path / "assets"
    )
    document_path = tmp_path / "Yearbook_of_Astronomy_2025.txt"
    document_path.write_text(
        "Yearbook of Astronomy 2025 introduction. This annual guide covers sky events, "
        "observing notes, lunar phases, planetary visibility, eclipses, meteor showers, "
        "and practical astronomy month by month.\n\n"
        "January observing notes mention Mars, Jupiter, winter constellations, and deep-sky targets.\n\n"
        "February observing notes discuss the Moon, Venus, and practical telescope planning.\n",
        encoding="utf-8",
    )
    library.import_document(document_path)

    assert DocumentKnowledgeLibrary.query_requests_document_brief(
        "Brief this document: 1"
    )

    context, visual_files, results = library.build_context_bundle(
        "Brief this document: 1"
    )

    assert visual_files == []
    assert results
    assert "DOCUMENT_BRIEF_REQUEST = TRUE" in context
    assert "Yearbook_of_Astronomy_2025.txt" in context
    assert "do not emit documents.brief" in context.lower()
    assert "observing notes" in context


def test_document_number_extraction_used_for_brief_selection(tmp_path):
    library = DocumentKnowledgeLibrary(
        tmp_path / "knowledge.sqlite3", asset_directory=tmp_path / "assets"
    )
    first = tmp_path / "first_book.txt"
    second = tmp_path / "second_book.txt"
    first.write_text("First document content about lunar observing.", encoding="utf-8")
    second.write_text(
        "Second document content about comet photography.", encoding="utf-8"
    )
    library.import_document(first)
    library.import_document(second)

    documents = library.list_documents()
    selected_ids = library._document_ids_for_brief_request(
        "Brief this document: 1", documents
    )

    assert selected_ids == [documents[0]["id"]]
