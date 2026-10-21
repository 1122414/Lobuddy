export interface MessageTransport {
  send(value: unknown): void;
  onMessage(listener: (value: unknown) => void): () => void;
  onClose(listener: () => void): () => void;
  close(): void;
}

/** Electron wraps the message in {data}; Node MessagePort delivers the value directly. */
export interface PortLike {
  postMessage(value: unknown): void;
  on(event: 'message' | 'close', listener: (...args: unknown[]) => void): unknown;
  off(event: 'message' | 'close', listener: (...args: unknown[]) => void): unknown;
  start(): void;
  close(): void;
}
export function portTransport(port: PortLike, envelope: 'electron' | 'node'): MessageTransport {
  port.start();
  return {
    send: value => port.postMessage(value), close: () => port.close(),
    onMessage: listener => {
      const receive = (value: unknown) => listener(envelope === 'electron' ? (value as { data: unknown }).data : value);
      port.on('message', receive); return () => { port.off('message', receive); };
    },
    onClose: listener => { port.on('close', listener); return () => { port.off('close', listener); }; },
  };
}
