/** Host-observed remote verification identity, attached only after stable gateway hashes. */
export interface RemoteVerificationArtifact {
  workspace_uri: string;
  artifact_uri: string;
  sha256: string;
  companion_session_id: string;
  execution_location: 'remote';
}
