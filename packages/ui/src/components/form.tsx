"use client";

import { type ReactNode, useId } from "react";
import {
  type Control,
  Controller,
  type ControllerRenderProps,
  type FieldPath,
  type FieldValues,
  FormProvider,
  type SubmitHandler,
  type UseFormReturn,
} from "react-hook-form";
import { cn } from "../lib/cn";
import { Label } from "./input";

export interface FormProps<T extends FieldValues> {
  form: UseFormReturn<T>;
  onSubmit: SubmitHandler<T>;
  children: ReactNode;
  className?: string;
}

/** A form wired to react-hook-form; the browser's own validation bubbles are turned off. */
export function Form<T extends FieldValues>({ form, onSubmit, children, className }: FormProps<T>) {
  return (
    <FormProvider {...form}>
      <form
        noValidate
        onSubmit={form.handleSubmit(onSubmit)}
        className={cn("grid gap-4", className)}
      >
        {children}
      </form>
    </FormProvider>
  );
}

export type FieldControlProps<
  T extends FieldValues,
  N extends FieldPath<T>,
> = ControllerRenderProps<T, N> & {
  id: string;
  "aria-invalid": boolean;
  "aria-describedby"?: string;
};

export interface FormFieldProps<T extends FieldValues, N extends FieldPath<T>> {
  control: Control<T>;
  name: N;
  label: string;
  description?: string;
  /** Render the control with the props that connect it to its label, description and error. */
  render: (field: FieldControlProps<T, N>) => ReactNode;
  className?: string;
}

export function FormField<T extends FieldValues, N extends FieldPath<T>>({
  control,
  name,
  label,
  description,
  render,
  className,
}: FormFieldProps<T, N>) {
  const id = useId();
  const descriptionId = `${id}-description`;
  const errorId = `${id}-error`;
  return (
    <Controller
      control={control}
      name={name}
      render={({ field, fieldState }) => {
        const message = fieldState.error?.message;
        const describedBy = [description ? descriptionId : null, message ? errorId : null]
          .filter(Boolean)
          .join(" ");
        return (
          <div className={cn("grid gap-1.5", className)}>
            <Label htmlFor={id}>{label}</Label>
            {render({
              ...field,
              id,
              "aria-invalid": Boolean(message),
              ...(describedBy ? { "aria-describedby": describedBy } : {}),
            })}
            {description ? (
              <p id={descriptionId} className="text-sm text-muted-foreground">
                {description}
              </p>
            ) : null}
            {message ? (
              <p id={errorId} role="alert" className="text-sm text-danger">
                {message}
              </p>
            ) : null}
          </div>
        );
      }}
    />
  );
}
