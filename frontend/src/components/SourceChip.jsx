function resolveLabel(source, fallbackLabel) {
        if (!source) {
                return fallbackLabel;
        }

        if (typeof source === "string") {
                return source;
        }

        return (
                source.title ||
                source.name ||
                source.label ||
                source.description ||
                fallbackLabel
        );
}

function resolveUrl(source) {
        if (!source || typeof source === "string") {
                return undefined;
        }

        return source.url || source.link || source.href || source.source_url;
}

function SourceChip({ source, index = 0 }) {
        if (!source) {
                return null;
        }

        const label = resolveLabel(source, `Source ${index + 1}`);
        const href = resolveUrl(source);

        return (
                <div className="chatbot-source-chip">
                        <span className="chatbot-source-chip__label">{label}</span>
                        {href ? (
                                <a
                                        href={href}
                                        target="_blank"
                                        rel="noreferrer"
                                        className="chatbot-source-chip__link"
                                >
                                        View source
                                </a>
                        ) : (
                                <span className="chatbot-source-chip__link chatbot-source-chip__link--disabled">
                                        View source
                                </span>
                        )}
                </div>
        );
}

export default SourceChip;
