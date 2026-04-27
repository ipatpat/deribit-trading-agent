# Design System: Serene Ledger (Aether Trade)

## Overview
A high-fidelity design system for a minimalist crypto trading and strategy platform, inspired by the warm, sophisticated aesthetic of Claude. It prioritizes clarity, intellectual calm, and structural elegance over the typical high-density "hacker" aesthetic of traditional crypto exchanges.

## Brand Values
- **Intellectual Clarity**: Clean layouts that reduce cognitive load.
- **Sophisticated Warmth**: A palette that feels human and trustworthy, moving away from "cold" tech blues and greens.
- **Precision**: Suble data visualization and clear typography for managing complex financial strategies.

---

## Visual Language

### 1. Color Palette
The palette is centered around "paper" and "stone" tones to create a tactile, grounded feeling.

| Color | Hex | Role | Usage |
| :--- | :--- | :--- | :--- |
| **Surface (Paper)** | `#FBF9F4` | Primary Background | Main application backgrounds and cards. |
| **Surface Dim** | `#EFECE6` | Secondary Background | Sidebars, secondary containers, and subtle dividers. |
| **Primary (Timber)** | `#7D5C4D` | Brand / Key Action | Primary buttons, brand logos, and active navigation states. |
| **Text Primary** | `#1A1A1A` | Main Content | Body copy, headers, and primary data points. |
| **Text Secondary** | `#6B6B6B` | Meta Data | Subtitles, labels, and secondary information. |
| **Success** | `#788475` | Positive Change | Percentage increases, "Buy" buttons (muted green). |
| **Danger** | `#A67B72` | Negative Change | Percentage decreases, "Sell" buttons (muted terracotta). |

### 2. Typography
A strong focus on serif fonts for headers to evoke a "ledger" or "newspaper" feel.

- **Primary Header Font**: `Newsreader` (or similar sophisticated Serif). Used for page titles and key metrics.
- **Body/System Font**: `Geist` or `Inter` (Clean Sans-Serif). Used for tabular data, labels, and input fields.
- **Data Font**: `JetBrains Mono` (Monospaced). Used for price numbers and balance values to ensure alignment.

**Hierarchy:**
- **H1 (Display)**: 48px / Semi-bold / Newsreader (Tracking: -0.02em)
- **H2 (Section Header)**: 24px / Medium / Newsreader
- **Body L**: 18px / Regular / Sans-Serif
- **Body S (Labels)**: 12px / Medium / Sans-Serif (Uppercase, letter-spacing: 0.05em)

### 3. Layout & Spacing
- **Grid**: 12-column desktop grid with 80px margins.
- **Border Radius**: `8px` (Round Eight) for a soft but professional look.
- **Elevation**: Minimal. Use subtle 1px borders (`#E2DDD2`) instead of heavy shadows.
- **Padding**: Generous whitespace between sections to prevent the UI from feeling cluttered.

---

## Core Components

### 1. Navigation Shell
- **TopAppBar**: Minimalist height. Displays total portfolio value in a subtle monospaced font. Market status indicator on the right.
- **SideNavBar**: Fixed width (260px). Uses `#EFECE6` background. Active states are indicated by a slight background shift to `#F9F7F2` and a bold serif label.

### 2. Cards & Modules
- **Information Cards**: White background (`#FFFFFF`) with a subtle 1px border. No shadows.
- **Strategy Blueprints**: Large list items with iconography and "Conservative/Moderate" badges using the secondary color palette.

### 3. Data Visualization
- **Charts**: Single-line area charts using the Primary color (`#7D5C4D`) with a subtle gradient fill.
- **Ledger Tables**: Clean rows with no vertical dividers. High contrast between the "Asset Name" (Serif) and the "Value" (Monospaced).

---

## Interaction Design
- **Hover States**: Subtle background color shifts (e.g., from `transparent` to `rgba(125, 92, 77, 0.05)`).
- **Transitions**: Ease-in-out (200ms) for all state changes.
- **Active States**: Tactile "pressed" effect for buttons (scale down to 98%).
