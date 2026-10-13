"""📜 Cross-service contracts: wire vocabulary shared by engine and gateway.

This package is deliberately dependency-free with respect to the rest of
Dionysus: no database, no LangChain/LangGraph, no socketio, no settings. It
holds only the shapes two sides of a boundary must agree on, so it can later
be extracted into a standalone ``dionysus-contracts`` distribution that the
gateway, the play engine, and the code generator for the frontend's
TypeScript types all depend on.

Keep it that way -- an import of anything domain-shaped here turns the
contracts into a distributed shared kernel and forces lockstep deploys.
"""
