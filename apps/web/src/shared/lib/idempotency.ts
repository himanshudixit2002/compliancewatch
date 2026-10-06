/**
 * The hidden form field that carries a write's Idempotency-Key from the render that minted it to
 * the server action that sends it as the header (server/api/idempotency.ts). It is named here,
 * outside the server layer, so a client form that builds its own FormData (a dialog's confirm, a
 * retry after a lost answer) can carry the key under the name the action reads.
 */
export const IDEMPOTENCY_KEY_FIELD = "idempotency_key";
