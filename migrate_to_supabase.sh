#!/bin/bash

# Supabase connection string
DATABASE_URL="postgresql://postgres:_7iKnvWvtWBXPWv@db.tdfwdwckvickqgmhcunf.supabase.co:5432/postgres"

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "Starting migration to Supabase..."

# Array of migration files in order
migrations=(
    "20240414161707_basejump-setup.sql"
    "20240414161947_basejump-accounts.sql"
    "20240414162100_basejump-invitations.sql"
    "20240414162131_basejump-billing.sql"
    "20250409211903_basejump-configure.sql"
    "20250409212058_initial.sql"
    "20250416133920_agentpress_schema.sql"
    "20250417000000_workflow_system.sql"
    "20250418000000_workflow_flows.sql"
    "20250504123828_fix_thread_select_policy.sql"
    "20250523133848_admin-view-access.sql"
    "20250524062639_agents_table.sql"
    "20250525000000_agent_versioning.sql"
    "20250526000000_secure_mcp_credentials.sql"
    "20250529125628_agent_marketplace.sql"
    "20250601000000_add_thread_metadata.sql"
    "20250602000000_add_custom_mcps_column.sql"
    "20250607000000_fix_encrypted_config_column.sql"
    "20250618000000_credential_profiles.sql"
    "20250624065047_secure_credentials.sql"
    "20250624093857_knowledge_base.sql"
    "20250626092143_agent_agnostic_thread.sql"
    "20250626114642_kortix_team_agents.sql"
    "20250630070510_agent_triggers.sql"
    "20250701082739_agent_knowledge_base.sql"
    "20250701083536_agent_kb_files.sql"
    "20250705155923_rollback_workflows.sql"
    "20250705161610_agent_workflows.sql"
    "20250705164211_fix_agent_workflows.sql"
    "20250706130554_simplify_workflow_steps.sql"
    "20250706130555_set_instruction_default.sql"
    "20250707140000_add_agent_run_metadata.sql"
    "20250708034613_add_steps_to_workflows.sql"
    "20250708123910_cleanup_db.sql"
    "20250722031718_agent_metadata.sql"
    "20250722034729_default_agent.sql"
    "20250723055703_nullable_system_prompt.sql"
    "20250723093053_fix_workflow_policy_conflicts.sql"
    "20250723175911_cleanup_agents_table.sql"
    "20250723181204_restore_avatar_columns.sql"
    "20250726174310_rem-devices-tables-responses_col.sql"
    "20250726180605_remove_old_workflow_sys.sql"
    "20250726184725_cleanup_schema_1.sql"
    "20250726200404_remove_agent_cols_from_threads.sql"
    "20250726223759_move_agent_fields_to_metadata.sql"
    "20250726224819_reverse_move_agent_fields_to_metadata.sql"
    "20250728193819_fix_templates.sql"
    "20250729094718_cleanup_agents_table.sql"
    "20250729105030_fix_agentpress_tools_sanitization.sql"
    "20250729110000_fix_pipedream_qualified_names.sql"
    "20250729120000_api_keys.sql"
    "20250808120000_supabase_cron.sql"
    "20250811133931_agent_profile_pic.sql"
    "20250811135257_supabase_pic_bucket.sql"
)

# Test connection first
echo "Testing database connection..."
if psql "$DATABASE_URL" -c "SELECT 1" > /dev/null 2>&1; then
    echo -e "${GREEN}Connection successful!${NC}"
else
    echo -e "${RED}Failed to connect to database. Please check your credentials.${NC}"
    exit 1
fi

# Run each migration
for migration in "${migrations[@]}"; do
    echo "Running migration: $migration"
    if psql "$DATABASE_URL" -f "backend/supabase/migrations/$migration" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ $migration${NC}"
    else
        echo -e "${RED}✗ Failed: $migration${NC}"
        echo "Attempting to continue with remaining migrations..."
    fi
done

echo ""
echo "Migration complete!"
echo "Verifying tables..."

# Verify key tables were created
psql "$DATABASE_URL" -c "
SELECT 
    'Tables created:' as info,
    COUNT(*) as count 
FROM pg_tables 
WHERE schemaname = 'public'
UNION ALL
SELECT 
    'Basejump tables:' as info,
    COUNT(*) as count 
FROM pg_tables 
WHERE schemaname = 'basejump';"

echo ""
echo "Key tables in public schema:"
psql "$DATABASE_URL" -c "
SELECT tablename 
FROM pg_tables 
WHERE schemaname = 'public' 
AND tablename IN ('agents', 'threads', 'messages', 'projects', 'agent_runs')
ORDER BY tablename;"