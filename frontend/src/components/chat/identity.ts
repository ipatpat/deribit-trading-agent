/**
 * Single source of truth for the AI assistant's display name.
 *
 * Frontend constant; the matching backend reference is a hardcoded line in
 * src/deribit_trading/agent/system_prompt.py ROLE section ("Your name is Vida.").
 * If you change AI_NAME, update both places.
 */
export const AI_NAME = 'Vida';
