/**
 * WebSocket hook for the chat stream.
 *
 * Implemented in T3.7; reconnection with exponential backoff is T5.5. The JWT
 * travels in the connection handshake — the socket is never trusted before the
 * server has verified it and confirmed session ownership.
 */

export {};
