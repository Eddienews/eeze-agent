import { useState, type FormEvent } from "react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

type ContactModalProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function ContactModal({ open, onOpenChange }: ContactModalProps) {
  const [state, setState] = useState<"idle" | "sending" | "ok" | "error">("idle");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setState("sending");
    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: form.get("email"),
          name: form.get("name"),
          message: form.get("message"),
          source: "landing",
        }),
      });
      if (!response.ok) throw new Error(`status ${response.status}`);
      setState("ok");
    } catch {
      setState("error");
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setState("idle");
      }}
    >
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Request access</DialogTitle>
          <DialogDescription>
            Tell us a bit about you and what you'd automate with Eeze.
          </DialogDescription>
        </DialogHeader>

        {state === "ok" ? (
          <div className="py-6 text-center">
            <p className="text-lg font-medium">Thanks — we'll be in touch.</p>
            <Button className="mt-6" onClick={() => onOpenChange(false)}>
              Close
            </Button>
          </div>
        ) : (
          <form className="grid gap-4" onSubmit={submit}>
            <Input
              name="email"
              type="email"
              required
              placeholder="you@company.com"
              aria-label="Email"
            />
            <Input name="name" placeholder="Your name" aria-label="Name" />
            <Textarea
              name="message"
              required
              rows={4}
              placeholder="What would you like Eeze to take care of?"
              aria-label="Message"
              className="resize-none"
            />
            {state === "error" && (
              <p className="text-sm text-destructive">
                Something went wrong. Please try again in a moment.
              </p>
            )}
            <Button type="submit" disabled={state === "sending"}>
              {state === "sending" ? "Sending…" : "Send"}
            </Button>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
