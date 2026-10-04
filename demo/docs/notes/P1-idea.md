We have created datasets ;

> **Location (4 Oct 2026):** this demo now lives in `demo/` and runs on its own (`demo/README.md`). Paths below are relative to `demo/`; the spec, `CLAUDE.md`, `docs/PROGRESS.md` and `datasets/` are at the repository root (`../`).

Made 384D embedding
We have noramlizaed it to length 1 and we have quanitzed it to 2^24 , 
First we took the vector embedding values and converted it to float64 for extra full prescision then we tunred that into quanzation and we ahve checked if any overflow exists 