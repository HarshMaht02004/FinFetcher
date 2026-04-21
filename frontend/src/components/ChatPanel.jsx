import { useState } from "react";

export default function ChatPanel({ reportId, messages, onSend, isQuerying }) {
  const [question, setQuestion] = useState("");

  async function handleSubmit(event) {
    event.preventDefault();
    if (!question.trim() || !reportId) {
      return;
    }
    await onSend(question.trim());
    setQuestion("");
  }

  return (
    <section className="panel">
      <div className="panel-heading">
        <span className="eyebrow">RAG QA</span>
        <h2>Ask grounded questions</h2>
        <p>
          Answers are generated against retrieved report context with a strict
          no-hallucination prompt.
        </p>
      </div>

      <div className="chat-thread">
        {messages.length === 0 ? (
          <div className="chat-placeholder">
            Try questions like “Compare net profit between years” or “What are key risks
            mentioned?”
          </div>
        ) : (
          messages.map((message) => (
            <article key={message.id} className={`chat-message chat-${message.role}`}>
              <span className="chat-role">{message.role === "user" ? "You" : "Analyst"}</span>
              <p>{message.content}</p>
            </article>
          ))
        )}
      </div>

      <form className="chat-form" onSubmit={handleSubmit}>
        <input
          type="text"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask about revenue growth, net profit, risks, liquidity..."
        />
        <button className="primary-button" type="submit" disabled={isQuerying || !reportId}>
          {isQuerying ? "Thinking..." : "Ask"}
        </button>
      </form>
    </section>
  );
}
