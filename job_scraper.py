from job_pipeline.pipeline import build_arg_parser, run_pipeline


if __name__ == "__main__":
    cli_args = build_arg_parser().parse_args()
    run_pipeline(output_file=cli_args.output)
