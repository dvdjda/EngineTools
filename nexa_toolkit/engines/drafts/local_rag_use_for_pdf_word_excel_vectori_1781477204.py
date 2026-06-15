"""DRAFT tool - generated from a request. Logic not filled. Not verified."""
from ...framework.contract import Engine, InputSpec, OutputSpec, register


@register
class Draft_local_rag_use_for_pdf_word_excel_vectori_1781477204(Engine):
    key = "local_rag_use_for_pdf_word_excel_vectori_1781477204"
    name = "Local RAG "
    kind = "local rag, ai"
    status = "draft"
    provenance = 'Local RAG \nUse for PDF, Word, Excel vectorization and storing locally to use locally installed OLLAMA. Serve as private RAG sever, no information going out of local storage to internet. Strictly private. Able to read source files including tabular data. Using bge-m3:latest for vectorization'
    notes = ("Draft skeleton generated from a request. The agent has not filled the "
             "real logic yet, so outputs echo the inputs and are marked unverified. "
             "Review, fill solve(), verify, then promote to trusted.")
    inputs = [
        InputSpec("value", "Value", "-", 0)
    ]

    def solve(self, v):
        # TODO: ask the assistant in chat to fill in the real logic for this tool.
        return dict(v)

    def outputs(self, v):
        return [
            OutputSpec("Value", v["value"], "-", "unverified", "{:.2f}")
        ]
