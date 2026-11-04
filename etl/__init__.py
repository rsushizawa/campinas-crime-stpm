"""ETL of campinas-crime-stpm: raw sources to the PostGIS warehouse.

    pipeline   Step / Pipeline / StepResult / RejectBuffer (pipes and filters)
    steps/     one module per stage: acquire, clean, units (treatment rules 1-22)
    load       write the release (rules 23-25) and the build row
    schemas    pandera checks on the loaded warehouse (stage 5)
    profile    data profile of the loaded tables
    acquire, clean, census, sources, postgis
               the rule functions and source readers the steps call
"""
