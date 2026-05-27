# Wheelspin Consume Stage Design

## Goal

Add a fifth automation stage that consumes acquired wheelspins after the existing car removal stage. This lets the pipeline turn wheelspin rewards back into CR before starting the next big loop.

## Pipeline

The default full pipeline becomes:

1. 循环跑图
2. 批量买车
3. 超级抽奖
4. 移除车辆
5. 开抽

Stage 4 should continue to stage 5 by default. Stage 5 should continue back to stage 1 by default.

## Image Templates

The stage uses these templates from `images/`:

- `SuperWheelSpin.png`
- `WheelSpin.png`
- `NoSuperSpinsLeft.png`
- `NoSpinsLeft.png`

The code should rely on the existing `get_img_path()` and template matching helpers so external image replacement still works.

## Stage Behavior

The new stage starts from the existing menu anchor by calling `enter_menu()`. From there it presses `PageDown` twice to reach the My Horizon area, then waits for either `SuperWheelSpin.png` or `WheelSpin.png`.

For super wheelspins:

1. If `SuperWheelSpin.png` is visible, click it.
2. Press `Enter` every 0.1 seconds while the spin flow is active.
3. Stop when either the My Horizon wheelspin icons are visible again or `NoSuperSpinsLeft.png` appears.
4. If the no-super-spins image appears, press `Enter` once and verify that the My Horizon wheelspin icons are visible again.

For regular wheelspins, repeat the same flow with `WheelSpin.png` and `NoSpinsLeft.png`.

After both spin types have been attempted, press `PageUp` twice to return toward the menu anchor and return success.

## UI And Config

Add a fifth card labeled `5. 开抽`. Add a fifth next-step control that supports steps 1 through 5. Add config keys for the fifth stage continuation behavior and any stage count/progress state needed for display.

Because the current top row is already wide, the UI can either widen the main window or reduce card widths slightly while preserving the existing visual style.

## Failure Handling

If the stage cannot reach My Horizon or cannot return from an empty-spin dialog, it should return `False` so the existing `attempt_recovery()` path can restore the menu anchor and retry from the same stage.

The new stage should honor `self.is_running` inside all loops and use the existing logging/status update helpers.
