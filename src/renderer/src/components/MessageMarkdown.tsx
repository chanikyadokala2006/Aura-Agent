import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface MessageMarkdownProps {
  content: string;
}

export function MessageMarkdown({ content }: MessageMarkdownProps) {
  return (
    <div className="prose prose-invert max-w-none prose-pre:bg-[#0c0c12] prose-pre:border prose-pre:border-[#232333] prose-pre:rounded-lg prose-a:text-cyan-400">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
