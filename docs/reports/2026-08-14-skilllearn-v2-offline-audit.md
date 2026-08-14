# SkillLearn clean-v2 offline audit

Date: 2026-08-14 UTC

This audit is provider-free. It validates local manifests, pinned Docker images,
the native execution/verifier path, feedback visibility, update acceptance, and
split isolation. It does not claim clean efficacy; that remains a three-seed
provider-backed result.

## Frozen v2 data and images

- All eight preregistered families were rebuilt without changing their v1
  instance order or 2/1/2-or-3 partition.
- The v2 family index contains 44 official instances. Its SHA-256 is
  `5e8d6558b44d30446ff7adb8f1fc96bb3075b20fa59170872c0e9e472094e8fc`.
- `prebuild_clean_skilllearn_images.py --require-existing` resolved every one
  of the 44 tasks to a prebuilt local image: 29 distinct context hashes, zero
  failures, `all_ready=true`. The image manifest SHA-256 is
  `0371a12a379a43e270e12a6eecaeca23d3b72c0ebe0b9f46c355ef37215a310b`.
- All committed manifests use `rsebench-methods://` locators and contain no
  absolute `/home/` path.

## Native execution evidence

The completed clean-v1 `offer-letter-generator` seed `20260813` is used only
as offline mechanism/calibration evidence. Its output is not copied into v2.

- The run contains 11 official `reward.txt` files and 11 CTRF verifier files,
  covering seed evaluation, two acquisition rounds, validation, and evolved
  evaluation. This confirms that containers started and the official verifier
  completed on every attempted episode in that run.
- Both acquisition rounds contain visible trajectories (13 and 16 tool
  events) and non-empty self-feedback diagnoses/recommendations. The seed skill
  is injected by the backend's system message and the executor exposes only
  acquisition feedback to reflection.
- The execution audit uses train IDs `offer-letter-generator-1/2` and the sole
  validation ID `offer-letter-generator-3`; held-out IDs `4/5/6` are absent
  from acquisition and validation.
- Two updates were accepted. Validation improved from `0.0` to `1.0`, and the
  evolved skill hash
  `d6c5d75073fceea662a0afba1edb76368a51ff22f55e2309423ba7d113c82773`
  differs from the seed hash
  `6ced3f9e76d49834c88d982c743d37d289d2726d95b4e4efaaa17e9c3fa51f9c`.

## Canary selection and limitations

`offer-letter-generator` is the clean-v2 SkillLearn canary because its
acquisition validation task improved from `0.0` to `1.0`. The selection uses
train/validation evidence only; it does not use v1 held-out scores. Its v2
manifest SHA-256 is
`06a3a9ac2a59bd079dfe8b97100f5127f96dfc3df270d1bd394ac177f197ef35`.

This is deliberately not reported as efficacy evidence. In the completed v1
run, the three-task held-out mean remained `0.3333 -> 0.3333`. By contrast,
`organize-messy-files` accepted two updates in each of three seeds but stayed
at validation `0.0 -> 0.0` and held-out `0.0 -> 0.0`; it is classified as a
seed/validation floor rather than an execution failure. The clean-v2 canary
must therefore still prove artifact update, accepted update, full verifier
coverage, and positive held-out gain under its new immutable identity.

## Audit decision

The SkillLearn baseline path is engineering-ready for a paid canary: instances,
containers, verifier output, prompt injection, visible feedback, validation
isolation, and semantic skill updates are all evidenced. It is not yet
efficacy-ready and cannot unlock N1-N4 until two of the three fixed clean-v2
seeds have strictly positive clean gain.
