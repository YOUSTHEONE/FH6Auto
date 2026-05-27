# Wheelspin Consume Stage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fifth `开抽` automation stage that consumes super wheelspins and regular wheelspins before the pipeline loops back to race.

**Architecture:** Keep the existing single-file app structure and add the new stage through the same UI/config/pipeline patterns as the first four stages. Add focused static regression tests that parse `main.py` so verification does not need game UI automation or Windows input side effects.

**Tech Stack:** Python, `unittest`, AST/source checks, CustomTkinter, existing OpenCV template matching helpers.

---

### Task 1: Static Regression Tests

**Files:**
- Create: `tests/test_wheelspin_stage_static.py`

- [ ] **Step 1: Write failing static tests**

Create tests that assert `main.py` contains the fifth stage defaults, UI label, pipeline dispatch, and wheelspin image templates.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m unittest tests.test_wheelspin_stage_static`

Expected before implementation: failures for missing `spin` pipeline stage and `5. 开抽` UI label.

### Task 2: Wire Stage 5 Into Config, UI, And Pipeline

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add config defaults**

Add `spin_count`, `chk_5`, and `next_5`. Change `next_4` default to `5`.

- [ ] **Step 2: Add UI card and next-step control**

Add a fifth card labeled `5. 开抽`, button command `self.start_pipeline("spin")`, and fifth next-step selector. Make step validation support `1..5`.

- [ ] **Step 3: Dispatch pipeline stage**

Change `steps` to `["race", "buy", "cj", "sell", "spin"]`, dispatch `"spin"` to `logic_consume_wheelspins`, and reset a new counter when a new big loop starts.

### Task 3: Implement Wheelspin Consumption Logic

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Add helper for one spin type**

Add a helper that clicks an available wheelspin image, presses `Enter` every 0.1 seconds, stops on either menu icon return or no-spins image, and confirms empty-state dialogs.

- [ ] **Step 2: Add `logic_consume_wheelspins`**

Start from `enter_menu()`, press `PageDown` twice, wait for wheelspin icons, process super wheelspins then regular wheelspins, press `PageUp` twice, update progress, and return success/failure.

### Task 4: Verify And Commit

**Files:**
- Modify: `main.py`
- Create: `tests/test_wheelspin_stage_static.py`
- Add: `images/SuperWheelSpin.png`
- Add: `images/WheelSpin.png`
- Add: `images/NoSuperSpinsLeft.png`
- Add: `images/NoSpinsLeft.png`

- [ ] **Step 1: Run verification**

Run:

```powershell
python -m unittest tests.test_wheelspin_stage_static
python -m py_compile main.py
git diff --check
```

- [ ] **Step 2: Commit**

Commit implementation and image templates with a feature message.
