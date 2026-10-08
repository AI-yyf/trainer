/** Only a host-bound card result can be shown on the currently displayed card. */
export function remoteVerificationEventMatchesDisplayedCard(
  eventCardId: string | undefined,
  displayedCardId: string | undefined,
): boolean {
  const authoritative = eventCardId?.trim();
  const displayed = displayedCardId?.trim();
  return Boolean(authoritative && displayed && authoritative === displayed);
}
