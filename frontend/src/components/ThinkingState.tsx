/** Waiting state. The bar breathes; under reduced motion it is static and the words carry it. */
export function ThinkingState({ text }: { text: string }) {
  return (
    <div className="text-ink-soft" role="status">
      <p className="mb-2 text-sm">{text}</p>
      <div className="thinking-bar" aria-hidden="true" />
    </div>
  )
}
