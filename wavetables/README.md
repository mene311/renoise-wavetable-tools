# Put your wavetables here

Drop one file per instrument and commit. Every file in this folder becomes one instrument,
and pushing here also starts the build.

Accepted: `.vitaltable`, `.vital` (Vital), `.wav` (Serum-style wavetables, N frames of 2048),
`.flac`, `.npy` (frames as an array).

Builds also run on demand: **Actions -> Build wavetable instruments -> Run workflow**, where you
can pick frames per instrument, frame selection, cycle length and whether to add the sweep
template. Results land in the run's **instruments** artifact.
