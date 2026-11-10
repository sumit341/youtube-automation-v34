YOUTUBE AUTOMATION - SAFE SOURCE VERIFICATION PATCH

Files:
- source_verification_v1.py: standalone HTTPS source fetcher, SHA-256 manifest, exact source_passage matching.

IMPORTANT:
1. This verifier intentionally never returns APPROVE. Exact quote presence proves only that the text appears in the fetched source, not that it logically supports the claim.
2. Existing evidence.csv may not contain source_passage. Add a source_passage column and put the exact source quotation there. Do not replace existing columns or delete rows.
3. PDF extraction is not enabled; PDF sources are held. This avoids pretending that a PDF was read when it was not.
4. Copy the module into app\source_verification_v1.py. Run from project root:
   python app\source_verification_v1.py --video-id E1irX9cDX8U
5. It writes source_verification_v1.json inside the pilot workspace. It does not modify source, claim, evidence, human decision, approval history, database, render, or upload files.
6. This is a new additive module, not a replacement for the workbench or approval engine. Keep your current files unchanged until the integration patch and tests are reviewed.
